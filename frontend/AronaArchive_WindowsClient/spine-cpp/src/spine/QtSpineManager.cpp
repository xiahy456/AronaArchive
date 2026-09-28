/*
 Copyright xia_hy456. All rights reserved.

 @Author: xia_hy456
 @Date: 2026/3/14 22:15:53

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      https://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

#include "spine/QtSpineManager.h"
#include "spine/QtTextureLoader.h"
#include <spine/Atlas.h>
#include <spine/SkeletonData.h>
#include <spine/Skeleton.h>
#include <spine/Bone.h>
#include <spine/Animation.h>
#include <spine/AnimationStateData.h>
#include <spine/AnimationState.h>
#include <spine/SkeletonBinary.h>
#include <spine/SkeletonJson.h>
#include <spine/RegionAttachment.h>
#include <spine/MeshAttachment.h>
#include <spine/Slot.h>
#include <QDebug>
#include <QHideEvent>
#include <QMatrix4x4>
#include <QShowEvent>
#include <cmath>
#include <cstddef>

namespace {
    constexpr float kSpineOriginX = 110.0f;
    constexpr float kSpineOriginY = 270.0f;
    constexpr float kSpineVisualScale = 0.2f;

    constexpr int kPatTrackA = 3;
    constexpr int kPatTrackM = 4;
    constexpr const char* kPatAnimA = "Pat_01_A";
    constexpr const char* kPatAnimM = "Pat_01_M";
    constexpr const char* kPatEndAnimA = "PatEnd_01_A";
    constexpr const char* kPatEndAnimM = "PatEnd_01_M";

    constexpr float kPatHitRadiusX = 140.0f;
    constexpr float kPatHitRadiusY = 100.0f;
    // 脸部控制点最大水平偏移（与 RangeX 一起决定跟随灵敏度）
    constexpr float kPatFollowMaxRadius = 40.0f;
    constexpr float kPatHeadTiltMaxDeg = 1.0f;
    // Head 转角与 Touch_Point_Key 共用：满偏所需世界单位，越小越灵敏
    constexpr float kPatHeadTiltRangeX = 160.0f;
    // t∈[-1,1] 每秒最大变化量。12 ≈ 满偏约 80ms，快甩时头会稍晚跟上
    constexpr float kPatFollowMaxSpeed = 12.0f;
    constexpr float kPatEndDuration = 0.067f;
    constexpr float kPatEndMixIn = 0.02f;
    constexpr float kPatEndMixOut = 0.08f;
}

QtSpineManager::QtSpineManager(QWidget* parent) : QOpenGLWidget(parent)
{
    // 作为 MainWidget 的子控件：透明背景即可，置顶/无边框只应由顶层窗口设置
    this->setAttribute(Qt::WA_TranslucentBackground);
    this->setAutoFillBackground(false);
    this->resize(220 * WIDGET_ZOOM, 440 * WIDGET_ZOOM);
    refreshSpineViewTransform();

    this->installEventFilter(this);

    m_elapsedTimer.start();
    m_renderLoopActive = true;
}

QtSpineManager::~QtSpineManager()
{
    m_renderLoopActive = false;
    makeCurrent();

    delete m_vbo;
    delete m_vao;
    delete m_program;
    m_batches.clear();

    doneCurrent();

    delete m_animationState;
    delete m_animationStateData;
    delete m_skeleton;
    delete m_skeletonData;
    delete m_atlas;
    delete m_textureLoader;
}

void QtSpineManager::initializeGL()
{
    initializeOpenGLFunctions();

    //glClearColor(0.69f, 0.88f, 0.90f, 0.0f);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);  // 完全透明黑色
    // 启用混合，使用正确的混合函数
    glEnable(GL_BLEND);
    glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);

    glDisable(GL_DEPTH_TEST);

    // 创建着色器程序
    m_program = new QOpenGLShaderProgram();

    const char* vertexShaderSource =
        "#version 330 core\n"
        "uniform mat4 u_matrix;\n"
        "layout(location = 0) in vec2 a_position;\n"
        "layout(location = 1) in vec2 a_texCoord;\n"
        "layout(location = 2) in vec4 a_color;\n"
        "out vec2 v_texCoord;\n"
        "out vec4 v_color;\n"
        "void main() {\n"
        "    gl_Position = u_matrix * vec4(a_position, 0.0, 1.0);\n"
        "    v_texCoord = vec2(a_texCoord.x, 1.0 - a_texCoord.y);\n"
        "    v_color = a_color;\n"
        "}\n";

    const char* fragmentShaderSource =
        "#version 330 core\n"
        "uniform sampler2D u_texture;\n"
        "uniform int u_premultiplied;\n"
        "in vec2 v_texCoord;\n"
        "in vec4 v_color;\n"
        "out vec4 fragColor;\n"
        "void main() {\n"
        "    vec4 texColor = texture(u_texture, v_texCoord);\n"
        "    \n"
        "    // PMA 贴图需要还原直通 RGB；直通 Alpha 贴图不可再除 alpha，否则边缘发白\n"
        "    if (u_premultiplied != 0 && texColor.a > 0.0) {\n"
        "        texColor.rgb /= texColor.a;\n"
        "    }\n"
        "    \n"
        "    // 再乘以顶点颜色\n"
        "    fragColor = texColor * v_color;\n"
        "    \n"
        "    // 丢弃几乎透明的像素\n"
        "    if (fragColor.a < 0.01) discard;\n"
        "}\n";

    m_program->addShaderFromSourceCode(QOpenGLShader::Vertex, vertexShaderSource);
    m_program->addShaderFromSourceCode(QOpenGLShader::Fragment, fragmentShaderSource);
    m_program->link();

    m_u_matrixLoc = m_program->uniformLocation("u_matrix");
    m_u_textureLoc = m_program->uniformLocation("u_texture");
    m_u_premultipliedLoc = m_program->uniformLocation("u_premultiplied");

    // 创建VBO / VAO，顶点布局只绑定一次
    m_vbo = new QOpenGLBuffer(QOpenGLBuffer::VertexBuffer);
    m_vbo->create();
    m_vbo->setUsagePattern(QOpenGLBuffer::DynamicDraw);

    m_vao = new QOpenGLVertexArrayObject();
    m_vao->create();

    m_vao->bind();
    m_vbo->bind();
    const size_t vertexSize = sizeof(SpineVertex);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, vertexSize, (void*)offsetof(SpineVertex, x));
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, vertexSize, (void*)offsetof(SpineVertex, u));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, vertexSize, (void*)offsetof(SpineVertex, r));
    glEnableVertexAttribArray(2);
    m_vbo->release();
    m_vao->release();

    FINE_DEBUG_OUTPUT("[Spine Operation]OpenGL initialized successfully");
    m_glReady = true;
    emit glReady();
    requestNextFrame();
}

void QtSpineManager::paintGL()
{
    glClear(GL_COLOR_BUFFER_BIT);

    updateAnimation();

    if (m_skeleton && m_program && m_program->isLinked()) {
        QMatrix4x4 projection;
        const int w = width();
        const int h = height();
        projection.ortho(0, w, h, 0, -1, 1);

        QMatrix4x4 transform;
        transform.translate(m_spineX, m_spineY);
        transform.scale(m_scale, -m_scale);

        QMatrix4x4 matrix = projection * transform;

        m_program->bind();
        m_program->setUniformValue(m_u_matrixLoc, matrix);
        m_program->setUniformValue(m_u_textureLoc, 0);

        m_usedBatches = 0;

        // Do not name this `slots`: Qt's `slots` macro would erase the identifier.
        spine::Vector<spine::Slot*>& drawOrder = m_skeleton->getDrawOrder();
        for (size_t i = 0; i < drawOrder.size(); ++i) {
            spine::Slot* slot = drawOrder[i];
            if (!slot) continue;

            spine::Attachment* attachment = slot->getAttachment();
            if (!attachment) continue;

            const spine::Color color = slot->getColor();

            if (attachment->getRTTI().instanceOf(spine::RegionAttachment::rtti)) {
                auto* regionAttachment = static_cast<spine::RegionAttachment*>(attachment);
                collectRegionAttachmentVertices(regionAttachment, slot, color);
            }
            else if (attachment->getRTTI().instanceOf(spine::MeshAttachment::rtti)) {
                auto* meshAttachment = static_cast<spine::MeshAttachment*>(attachment);
                collectMeshAttachmentVertices(meshAttachment, slot, color);
            }
        }

        flushBatches();
        m_program->release();
    }

    requestNextFrame();
}

void QtSpineManager::resizeGL(int w, int h)
{
    glViewport(0, 0, w, h);
    m_cachedZoom = -1.0f;
    refreshSpineViewTransform();
}

void QtSpineManager::showEvent(QShowEvent* event)
{
    QOpenGLWidget::showEvent(event);
    m_renderLoopActive = true;
    requestNextFrame();
}

void QtSpineManager::hideEvent(QHideEvent* event)
{
    m_renderLoopActive = false;
    QOpenGLWidget::hideEvent(event);
}

void QtSpineManager::requestNextFrame()
{
    if (m_renderLoopActive) {
        update();
    }
}

void QtSpineManager::mousePressEvent(QMouseEvent* event)
{
    if (event->button() == Qt::LeftButton) {
        m_leftDown = true;
        updateMouseWorldFromWidget(event->position());
        if (!m_patActive && isInPatHitBox(m_mouseWorld)) {
            handlePat();
        }
    }

    QOpenGLWidget::mousePressEvent(event);
}

void QtSpineManager::mouseReleaseEvent(QMouseEvent* event)
{
    if (event->button() == Qt::LeftButton) {
        m_leftDown = false;
        if (m_patActive) {
            handlePatEnd();
        }
    }

    QOpenGLWidget::mouseReleaseEvent(event);
}

void QtSpineManager::mouseMoveEvent(QMouseEvent* event)
{
    if (m_leftDown || (event->buttons() & Qt::LeftButton)) {
        updateMouseWorldFromWidget(event->position());
    }

    QOpenGLWidget::mouseMoveEvent(event);
}

void QtSpineManager::updateAnimation()
{
    if (!m_animationState || !m_skeleton) {
        return;
    }

    const qint64 nowNs = m_elapsedTimer.nsecsElapsed();
    float deltaTime = static_cast<float>(nowNs - m_lastTimeNs) / 1000000000.0f;
    m_lastTimeNs = nowNs;

    if (deltaTime > 0.1f) {
        deltaTime = 0.1f;
    }
    if (deltaTime <= 0.0f) {
        return;
    }

    m_animationState->update(deltaTime);
    m_animationState->apply(*m_skeleton);
    if (m_patActive || m_patEnding) {
        // 先得到不含额外转头的世界矩阵，避免用上一帧倾斜去算跟随而放大
        m_skeleton->updateWorldTransform(spine::Physics_Update);
        if (m_patEnding) {
            m_patEndElapsed += deltaTime;
            const float u = qBound(0.0f, m_patEndElapsed / kPatEndDuration, 1.0f);
            const float s = u * u * (3.0f - 2.0f * u);
            applyPatFollow(m_patEndFromT * (1.0f - s));
            if (u >= 1.0f) {
                m_patEnding = false;
            }
        } else {
            applyPatFollow(stepPatFollowT(computePatFollowT(), deltaTime));
        }
    }
    m_skeleton->updateWorldTransform(spine::Physics_Update);
}

void QtSpineManager::loadSpineFile(const QString& atlasPath, const QString& skelOrJsonPath)
{
    QElapsedTimer loadTimer;
    loadTimer.start();
    m_textureLoader = new QtTextureLoader();
    m_atlas = new spine::Atlas(atlasPath.toStdString().c_str(), m_textureLoader);

    if (!m_atlas) {
        ERROR_DEBUG_OUTPUT("Failed to load atlas:" + atlasPath);
        emit spineLoaded();
        return;
    }

    // 尊重 atlas 中的 pma 标记（缺省为 false）；勿强制覆盖，否则直通 Alpha 贴图会被错误反预乘

    bool isBinary = skelOrJsonPath.endsWith(".skel", Qt::CaseInsensitive);

    if (isBinary) {
        spine::SkeletonBinary binary(m_atlas);
        m_skeletonData = binary.readSkeletonDataFile(skelOrJsonPath.toStdString().c_str());
    }
    else {
        spine::SkeletonJson json(m_atlas);
        m_skeletonData = json.readSkeletonDataFile(skelOrJsonPath.toStdString().c_str());
    }

    if (!m_skeletonData) {
        ERROR_DEBUG_OUTPUT("Failed to load skeleton data:" + skelOrJsonPath);
        emit spineLoaded();
        return;
    }

    m_skeleton = new spine::Skeleton(m_skeletonData);
    m_animationStateData = new spine::AnimationStateData(m_skeletonData);
    m_defaultMix = static_cast<float>(GET_DOUBLE_FROM_JSON(_global_config, "spine", "animation_default_mix"));
    m_animationStateData->setDefaultMix(m_defaultMix);
    m_animationState = new spine::AnimationState(m_animationStateData);
    m_skeleton->setToSetupPose();
    refreshSpineViewTransform();
    cachePatBones();
    logPatAnimations();
    m_skeleton->updateWorldTransform(spine::Physics_Update);

    FINE_DEBUG_OUTPUT(QString("[Startup] Spine file loaded: %1 ms").arg(loadTimer.elapsed()));
    FINE_DEBUG_OUTPUT("[Spine Operation]Spine file loaded successfully!");
    emit spineLoaded();
}

void QtSpineManager::setAnimation(const QString& name, int track_idx, bool loop)
{
    if (!m_animationState || !m_skeletonData) {
        ERROR_DEBUG_OUTPUT("[Spine Operation]Animation state not ready");
        return;
    }

    spine::Animation* anim = m_skeletonData->findAnimation(name.toStdString().c_str());
    if (anim) {
        spine::TrackEntry* entry = m_animationState->setAnimation(track_idx, anim, loop);
        if (entry) {
            entry->setMixDuration(m_defaultMix);
        }
        FINE_DEBUG_OUTPUT("[Spine Operation]Set animation:" + name);
    }
    else {
        ERROR_DEBUG_OUTPUT("[Spine Operation]Animation not found:" + name);
    }
}

void QtSpineManager::clearAnimation(int track_idx, float mix_duration)
{
    if (!m_animationState) return;
    m_animationState->setEmptyAnimation(track_idx, mix_duration);
    FINE_DEBUG_OUTPUT("[Spine Operation]Cleared animation on track:" + QString::number(track_idx));
}

void QtSpineManager::collectMeshAttachmentVertices(spine::MeshAttachment* attachment,
    spine::Slot* slot,
    const spine::Color& slotColor)
{
    if (!attachment || !slot) return;

    GLuint textureId = getTextureId(attachment);
    if (textureId == 0) return;
    const bool premultiplied = getTexturePremultiplied(attachment);

    int numVertices = attachment->getWorldVerticesLength();
    if (numVertices <= 0) return;

    spine::Vector<unsigned short>& triangles = attachment->getTriangles();
    if (triangles.size() < 3) return;

    spine::Vector<float>& uvs = attachment->getUVs();
    if (uvs.size() < static_cast<size_t>(numVertices)) return;

    // 获取附件的颜色
    spine::Color attachmentColor = attachment->getColor();

    // 计算最终颜色
    float finalR = slotColor.r * attachmentColor.r;
    float finalG = slotColor.g * attachmentColor.g;
    float finalB = slotColor.b * attachmentColor.b;
    float finalA = slotColor.a * attachmentColor.a;

    // 如果透明度为0，跳过渲染
    if (finalA <= 0.0f) return;

    TextureBatch* batch = acquireBatch(textureId, premultiplied);
    if (!batch) return;

    if (m_worldVertices.size() < static_cast<size_t>(numVertices)) {
        m_worldVertices.resize(static_cast<size_t>(numVertices));
    }
    attachment->computeWorldVertices(*slot, 0, numVertices, m_worldVertices.data(), 0, 2);

    int vertexCount = numVertices / 2;
    int triangleCount = static_cast<int>(triangles.size() / 3);
    batch->vertices.reserve(batch->vertices.size() + triangleCount * 3);

    for (int i = 0; i < triangleCount; ++i) {
        int baseIdx = i * 3;
        if (baseIdx + 2 >= (int)triangles.size()) break;

        int idx1 = triangles[baseIdx];
        int idx2 = triangles[baseIdx + 1];
        int idx3 = triangles[baseIdx + 2];

        if (idx1 >= vertexCount || idx2 >= vertexCount || idx3 >= vertexCount) continue;

        int indices[3] = { idx1, idx2, idx3 };
        for (int j = 0; j < 3; ++j) {
            int idx = indices[j];
            int worldIdx = idx * 2;
            int uvIdx = idx * 2;

            if (worldIdx + 1 >= numVertices || uvIdx + 1 >= (int)uvs.size()) continue;

            SpineVertex vertex;
            vertex.x = m_worldVertices[worldIdx];
            vertex.y = m_worldVertices[worldIdx + 1];
            vertex.u = uvs[uvIdx];
            vertex.v = uvs[uvIdx + 1];
            vertex.r = finalR;
            vertex.g = finalG;
            vertex.b = finalB;
            vertex.a = finalA;

            batch->vertices.append(vertex);
        }
    }
}

void QtSpineManager::collectRegionAttachmentVertices(spine::RegionAttachment* attachment,
    spine::Slot* slot,
    const spine::Color& slotColor)
{
    if (!attachment || !slot) return;

    GLuint textureId = getTextureId(attachment);
    if (textureId == 0) return;
    const bool premultiplied = getTexturePremultiplied(attachment);

    float worldVertices[8];
    attachment->computeWorldVertices(*slot, worldVertices, 0, 2);

    float uvs[8];
    for (int i = 0; i < 8; i++) {
        if (i < attachment->getUVs().size()) {
            uvs[i] = attachment->getUVs()[i];
        }
    }

    // 获取附件颜色
    spine::Color attachmentColor = attachment->getColor();

    // 计算最终颜色
    float finalR = slotColor.r * attachmentColor.r;
    float finalG = slotColor.g * attachmentColor.g;
    float finalB = slotColor.b * attachmentColor.b;
    float finalA = slotColor.a * attachmentColor.a;

    // 如果透明度为0，跳过渲染
    if (finalA <= 0.0f) return;

    TextureBatch* batch = acquireBatch(textureId, premultiplied);
    if (!batch) return;

    batch->vertices.reserve(batch->vertices.size() + 6);
    batch->vertices.append({ worldVertices[0], worldVertices[1], uvs[0], uvs[1], finalR, finalG, finalB, finalA });
    batch->vertices.append({ worldVertices[2], worldVertices[3], uvs[2], uvs[3], finalR, finalG, finalB, finalA });
    batch->vertices.append({ worldVertices[4], worldVertices[5], uvs[4], uvs[5], finalR, finalG, finalB, finalA });
    batch->vertices.append({ worldVertices[2], worldVertices[3], uvs[2], uvs[3], finalR, finalG, finalB, finalA });
    batch->vertices.append({ worldVertices[6], worldVertices[7], uvs[6], uvs[7], finalR, finalG, finalB, finalA });
    batch->vertices.append({ worldVertices[4], worldVertices[5], uvs[4], uvs[5], finalR, finalG, finalB, finalA });
}

void QtSpineManager::flushBatches()
{
    if (m_usedBatches <= 0 || !m_vbo || !m_vao) return;

    m_vao->bind();
    m_vbo->bind();

    for (int i = 0; i < m_usedBatches; ++i) {
        const TextureBatch& batch = m_batches[i];
        if (batch.vertices.isEmpty() || batch.textureId == 0) continue;

        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, batch.textureId);
        m_program->setUniformValue(m_u_premultipliedLoc, batch.premultiplied ? 1 : 0);

        const int dataSize = batch.vertices.size() * static_cast<int>(sizeof(SpineVertex));
        if (dataSize > m_vboAllocatedBytes) {
            m_vboAllocatedBytes = dataSize + dataSize / 2;
            m_vbo->allocate(m_vboAllocatedBytes);
        }
        m_vbo->write(0, batch.vertices.constData(), dataSize);
        glDrawArrays(GL_TRIANGLES, 0, batch.vertices.size());
    }

    m_vao->release();
    m_vbo->release();
}

QtSpineManager::TextureBatch* QtSpineManager::acquireBatch(GLuint textureId, bool premultiplied)
{
    if (m_usedBatches > 0) {
        TextureBatch& last = m_batches[m_usedBatches - 1];
        if (last.textureId == textureId && last.premultiplied == premultiplied) {
            return &last;
        }
    }

    if (m_usedBatches < m_batches.size()) {
        TextureBatch& batch = m_batches[m_usedBatches];
        batch.textureId = textureId;
        batch.premultiplied = premultiplied;
        batch.vertices.clear();
        ++m_usedBatches;
        return &batch;
    }

    TextureBatch batch;
    batch.textureId = textureId;
    batch.premultiplied = premultiplied;
    batch.vertices.reserve(4096);
    m_batches.append(batch);
    ++m_usedBatches;
    return &m_batches.last();
}

void QtSpineManager::setAttachmentRelativeTransform(const QString& slotName, float offsetX, float offsetY, float rotation, float scaleX, float scaleY)
{
    //spine::Slot* slot = m_skeleton->findSlot(slotName.toStdString().c_str());
    //if (!slot) return;

    //spine::Attachment* attachment = slot->getAttachment();
    //if (!attachment) return;

    //// 对于RegionAttachment
    //if (attachment->getRTTI().instanceOf(spine::RegionAttachment::rtti)) {
    //    auto* regionAtt = static_cast<spine::RegionAttachment*>(attachment);

    //    // 获取原始的局部变换（相对于骨骼）
    //    float originalX = regionAtt->getX();
    //    float originalY = regionAtt->getY();
    //    float originalRotation = regionAtt->getRotation();
    //    float originalScaleX = regionAtt->getScaleX();
    //    float originalScaleY = regionAtt->getScaleY();

    //    // 设置新的相对变换（这些值是相对于骨骼的）
    //    regionAtt->setX(originalX + offsetX);
    //    regionAtt->setY(originalY + offsetY);
    //    regionAtt->setRotation(originalRotation + rotation);
    //    regionAtt->setScaleX(originalScaleX * scaleX);
    //    regionAtt->setScaleY(originalScaleY * scaleY);

    //    // 更新Attachment的偏移矩阵
    //    regionAtt->updateOffset();
    //}
    //// 对于MeshAttachment
    //else if (attachment->getRTTI().instanceOf(spine::MeshAttachment::rtti)) {
    //    auto* meshAtt = static_cast<spine::MeshAttachment*>(attachment);

    //    // MeshAttachment有类似的相对变换属性
    //    meshAtt->setRelativeX(meshAtt->getRelativeX() + offsetX);
    //    meshAtt->setRelativeY(meshAtt->getRelativeY() + offsetY);
    //    meshAtt->setRelativeRotation(meshAtt->getRelativeRotation() + rotation);
    //    meshAtt->setRelativeScaleX(meshAtt->getRelativeScaleX() * scaleX);
    //    meshAtt->setRelativeScaleY(meshAtt->getRelativeScaleY() * scaleY);

    //    // 需要重新计算顶点
    //    meshAtt->updateUVs();
    //}
}

void QtSpineManager::refreshSpineViewTransform()
{
    const float zoom = static_cast<float>(WIDGET_ZOOM);
    if (m_cachedZoom == zoom) {
        return;
    }
    m_cachedZoom = zoom;
    m_spineX = kSpineOriginX * zoom;
    m_spineY = kSpineOriginY * zoom;
    m_scale = kSpineVisualScale * zoom;
}

QPointF QtSpineManager::widgetToSpineWorld(const QPointF& widgetPos) const
{
    if (m_scale == 0.0f) {
        return QPointF();
    }
    return QPointF(
        (widgetPos.x() - m_spineX) / m_scale,
        (widgetPos.y() - m_spineY) / -m_scale
    );
}

void QtSpineManager::updateMouseWorldFromWidget(const QPointF& widgetPos)
{
    m_mouseWorld = widgetToSpineWorld(widgetPos);
}

bool QtSpineManager::isInPatHitBox(const QPointF& spineWorld) const
{
    if (!m_patHitBone) {
        return false;
    }
    const float dx = static_cast<float>(spineWorld.x()) - m_patHitBone->getWorldX();
    const float dy = static_cast<float>(spineWorld.y()) - m_patHitBone->getWorldY();
    if (kPatHitRadiusX <= 0.0f || kPatHitRadiusY <= 0.0f) {
        return false;
    }
    const float nx = dx / kPatHitRadiusX;
    const float ny = dy / kPatHitRadiusY;
    return (nx * nx + ny * ny) <= 1.0f;
}

void QtSpineManager::cachePatBones()
{
    m_touchPointBone = nullptr;
    m_touchPointKeyBone = nullptr;
    m_headBone = nullptr;
    m_patHitBone = nullptr;

    if (!m_skeleton) {
        return;
    }

    m_touchPointBone = m_skeleton->findBone("Touch_Point");
    m_touchPointKeyBone = m_skeleton->findBone("Touch_Point_Key");
    m_headBone = m_skeleton->findBone("Head");
    m_patHitBone = m_touchPointBone ? m_touchPointBone : m_headBone;

    if (m_touchPointBone) {
        FINE_DEBUG_OUTPUT("[Spine Operation]Pat hit bone: Touch_Point");
    } else if (m_patHitBone) {
        FINE_DEBUG_OUTPUT("[Spine Operation]Pat hit bone fallback: Head");
    } else {
        ERROR_DEBUG_OUTPUT("[Spine Operation]Pat hit bone not found (Touch_Point / Head)");
    }
}

void QtSpineManager::logPatAnimations()
{
    if (!m_skeletonData) {
        return;
    }

    const char* names[] = { kPatAnimA, kPatAnimM, kPatEndAnimA, kPatEndAnimM };
    for (const char* name : names) {
        spine::Animation* anim = m_skeletonData->findAnimation(name);
        if (anim) {
            FINE_DEBUG_OUTPUT(QString("[Spine Operation]Found animation %1 duration=%2")
                .arg(name)
                .arg(anim->getDuration(), 0, 'f', 4));
        } else {
            ERROR_DEBUG_OUTPUT(QString("[Spine Operation]Animation not found: %1").arg(name));
        }
    }
}

void QtSpineManager::holdPatAnimation(int track_idx, const char* name)
{
    if (!m_animationState || !m_skeletonData) {
        ERROR_DEBUG_OUTPUT("[Spine Operation]Animation state not ready");
        return;
    }

    spine::Animation* anim = m_skeletonData->findAnimation(name);
    if (!anim) {
        ERROR_DEBUG_OUTPUT(QString("[Spine Operation]Animation not found:") + name);
        return;
    }

    spine::TrackEntry* entry = m_animationState->setAnimation(track_idx, anim, true);
    if (!entry) {
        return;
    }
    entry->setLoop(true);
    entry->setTimeScale(0.0f);
    entry->setTrackEnd(1.0e9f);
    FINE_DEBUG_OUTPUT(QString("[Spine Operation]Hold pat animation: %1 on track %2").arg(name).arg(track_idx));
}

void QtSpineManager::handlePat()
{
    m_patEnding = false;
    m_patPressTimer.start();
    holdPatAnimation(kPatTrackA, kPatAnimA);
    holdPatAnimation(kPatTrackM, kPatAnimM);
    m_patActive = true;
    if (m_animationState && m_skeleton) {
        m_animationState->apply(*m_skeleton);
        m_skeleton->updateWorldTransform(spine::Physics_Update);
        applyPatFollow(computePatFollowT());
        m_skeleton->updateWorldTransform(spine::Physics_Update);
        update();
    }
}

void QtSpineManager::playPatEndAnimation(int track_idx, const char* name)
{
    if (!m_animationState || !m_skeletonData) {
        return;
    }

    spine::Animation* anim = m_skeletonData->findAnimation(name);
    if (!anim) {
        ERROR_DEBUG_OUTPUT(QString("[Spine Operation]Animation not found:") + name);
        return;
    }

    spine::TrackEntry* entry = m_animationState->setAnimation(track_idx, anim, false);
    if (!entry) {
        return;
    }
    entry->setLoop(false);
    entry->setMixDuration(kPatEndMixIn);
    const float duration = anim->getDuration() > 0.0f ? anim->getDuration() : kPatEndDuration;
    m_animationState->addEmptyAnimation(track_idx, kPatEndMixOut, duration);
}

void QtSpineManager::handlePatEnd()
{
    m_patActive = false;
    m_patEnding = true;
    m_patEndElapsed = 0.0f;
    m_patEndFromT = m_patFollowT;

    playPatEndAnimation(kPatTrackA, kPatEndAnimA);
    playPatEndAnimation(kPatTrackM, kPatEndAnimM);

    if (m_skeleton && m_animationState) {
        m_animationState->apply(*m_skeleton);
        m_skeleton->updateWorldTransform(spine::Physics_Update);
        applyPatFollow(m_patEndFromT);
        m_skeleton->updateWorldTransform(spine::Physics_Update);
        update();
    }
    const int durationMs = m_patPressTimer.isValid()
        ? static_cast<int>(m_patPressTimer.elapsed())
        : 0;
    emit patEnded(durationMs);
    FINE_DEBUG_OUTPUT(QString("[Spine Operation]Pat end durationMs=%1").arg(durationMs));
}

float QtSpineManager::computePatFollowT() const
{
    if (!m_touchPointBone) {
        return 0.0f;
    }
    const float relx = static_cast<float>(m_mouseWorld.x()) - m_touchPointBone->getWorldX();
    return qBound(-1.0f, relx / kPatHeadTiltRangeX, 1.0f);
}

float QtSpineManager::stepPatFollowT(float target, float dt)
{
    const float maxDelta = kPatFollowMaxSpeed * dt;
    const float delta = target - m_patFollowT;
    if (std::abs(delta) <= maxDelta) {
        m_patFollowT = target;
    } else {
        m_patFollowT += (delta > 0.0f ? maxDelta : -maxDelta);
    }
    return m_patFollowT;
}

void QtSpineManager::applyPatFollow(float t)
{
    if (!m_touchPointBone || !m_touchPointKeyBone) {
        return;
    }

    m_patFollowT = t;

    // 只跟随鼠标水平位移：世界 Y 钉在额头控制点上，避免头被上下拽
    const float boneWorldX = m_touchPointBone->getWorldX();
    const float boneWorldY = m_touchPointBone->getWorldY();
    const float followX = boneWorldX + t * kPatFollowMaxRadius;

    float localX = 0.0f;
    float localY = 0.0f;
    m_touchPointBone->worldToLocal(followX, boneWorldY, localX, localY);

    m_touchPointKeyBone->setX(localX);
    m_touchPointKeyBone->setY(localY);

    // 转 Head 而不是 Head_Rot：光环 / 后脑勺挂在 Head 下，才能一起跟
    if (m_headBone) {
        m_headBone->setRotation(m_headBone->getRotation() + t * kPatHeadTiltMaxDeg);
    }
}

GLuint QtSpineManager::getTextureId(spine::RegionAttachment* attachment)
{
    if (!attachment) return 0;

    // RegionAttachment可以通过getRegion()获取TextureRegion
    spine::TextureRegion* region = attachment->getRegion();
    if (!region) return 0;

    // 从TextureRegion获取AtlasRegion
    spine::AtlasRegion* atlasRegion = static_cast<spine::AtlasRegion*>(region);
    if (!atlasRegion || !atlasRegion->page) return 0;

    // 直接从page.texture获取纹理ID指针
    GLuint* textureIdPtr = static_cast<GLuint*>(atlasRegion->page->texture);
    if (!textureIdPtr) return 0;

    return *textureIdPtr;
}

GLuint QtSpineManager::getTextureId(spine::MeshAttachment* attachment)
{
    if (!attachment) return 0;

    // MeshAttachment也有getRegion()方法
    spine::TextureRegion* region = attachment->getRegion();
    if (!region) return 0;

    spine::AtlasRegion* atlasRegion = static_cast<spine::AtlasRegion*>(region);
    if (!atlasRegion || !atlasRegion->page) return 0;

    GLuint* textureIdPtr = static_cast<GLuint*>(atlasRegion->page->texture);
    if (!textureIdPtr) return 0;

    return *textureIdPtr;
}

bool QtSpineManager::getTexturePremultiplied(spine::RegionAttachment* attachment)
{
    if (!attachment) return false;
    spine::TextureRegion* region = attachment->getRegion();
    if (!region) return false;
    spine::AtlasRegion* atlasRegion = static_cast<spine::AtlasRegion*>(region);
    return atlasRegion && atlasRegion->page && atlasRegion->page->pma;
}

bool QtSpineManager::getTexturePremultiplied(spine::MeshAttachment* attachment)
{
    if (!attachment) return false;
    spine::TextureRegion* region = attachment->getRegion();
    if (!region) return false;
    spine::AtlasRegion* atlasRegion = static_cast<spine::AtlasRegion*>(region);
    return atlasRegion && atlasRegion->page && atlasRegion->page->pma;
}
