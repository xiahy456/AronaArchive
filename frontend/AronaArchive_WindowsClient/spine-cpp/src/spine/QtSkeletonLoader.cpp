#include <spine/QtSkeletonLoader.h>

QtSkeletonLoader::QtSkeletonLoader(const std::string& atlasPath, const std::string& skeletonJsonPath)
    : m_atlasPath(spine::String(atlasPath.c_str()))
    , m_skeletonJsonPath(spine::String(skeletonJsonPath.c_str()))
{
    QSurfaceFormat format;
    format.setVersion(3, 3);  // 使用OpenGL 3.3 Core Profile
    format.setProfile(QSurfaceFormat::CoreProfile);
    format.setDepthBufferSize(24);
    format.setStencilBufferSize(8);
    format.setSamples(4);  // 开启抗锯齿
    setFormat(format);
    if (!Load())
    {
        this->~QtSkeletonLoader();
    }
}

bool QtSkeletonLoader::Load()
{
    m_atlas = std::make_unique<spine::Atlas>(m_atlasPath, &m_QtTextureLoader);
    qDebug() << "===== Loading Spine Resources =====";
    qDebug() << "[Spine Operation] Atlas Path: " << m_atlasPath.buffer();
    qDebug() << "[Spine Operation] Skeleton Json Path: " << m_skeletonJsonPath.buffer();

    if (m_atlas == nullptr) {
        qDebug() << "[Atlas] Pointer is null，atlasPath went wrong!";
        return false;
    }
    // 强制触发Atlas实际加载（解决懒加载问题）
    // 访问getPages()会让Spine解析atlas文件、调用QtTextureLoader加载图片
    size_t pageCount = m_atlas->getPages().size();
    size_t regionCount = m_atlas->getRegions().size();

    // 校验Atlas是否真的加载成功（非空+有页面/区域）
    if (pageCount > 0 && regionCount > 0) {
        qDebug() << "[Spine Operation] Texture load succeed!";
        qDebug() << "[Spine Operation] Texture Big-textures amount: " << pageCount << " | Small-texture amount: " << regionCount;

        // 1. 创建AtlasAttachmentLoader → 核心桥梁：连接Atlas和骨骼 (就是拿出工具，准备使用)
        // 原理：SkeletonJson解析骨骼文件时，通过它调用atlas->findRegion()根据名称匹配素材
        spine::AtlasAttachmentLoader attachmentLoader(m_atlas.get());
        // 2. 创建SkeletonJson解析器 → 专门解析Spine导出的.json骨骼配置文件
        spine::SkeletonJson skeletonJson(&attachmentLoader);
        // 3. 解析.json文件，生成SkeletonData（骨骼核心数据：包含所有骨骼/附件/插槽/皮肤等信息）
        spine::SkeletonData* tempData = skeletonJson.readSkeletonDataFile(spine::String(m_skeletonJsonPath.buffer()));
        // 安全的话，就交给智能指针管理
        if (tempData) {
            m_skeletonData.reset(tempData); // 智能指针接管内存，自动析构
            qDebug() << "Version: " << m_skeletonData->getVersion().buffer();
            qDebug() << "[Spine Operation] Skeleton Load Succeed! [No Animations]";
            qDebug() << "[Spine Operation] Skeleton Amount: " << m_skeletonData->getBones().size();
            qDebug() << "[Spine Operation] Slots Amount: " << m_skeletonData->getSlots().size();
            qDebug() << "[Spine Operation] Skins Amount: " << m_skeletonData->getSkins().size();
        }
        else {
            qDebug() << "[Spine Operation] Skeleton Load Failed! Reason：" << skeletonJson.getError().buffer();
            m_atlas.reset(); // 素材加载成功但骨骼解析失败，释放Atlas避免内存泄漏
            m_skeletonData.reset(); // 兜底置空
        }
    }
    return true;

}

bool QtSkeletonLoader::ModelCreate(const std::string& atlasPath, const std::string& skeletonJsonPath)
{
    // 创建AnimationStateData
	m_animationStateData = new spine::AnimationStateData(m_skeletonData.get());
    // 设置默认过渡动画时间
	m_animationStateData->setDefaultMix(0.2f); // 0.2秒的默认过渡时间
	// 创建AnimationState
    m_animationState = new spine::AnimationState(m_animationStateData);
    qDebug() << "[Spine Operation] Animation Assets Create Succeed!";
    // 创建骨骼对象
	m_skeleton = new spine::Skeleton(m_skeletonData.get());
	return true;
}

bool QtSkeletonLoader::PlayAnimation(const QString& animationName, bool loop)
{
    if (!m_animationState || !m_skeletonData) return false;

    // 获取动画索引（或者直接用名字）
    int trackIndex = 0;  // 使用轨道0
    bool loop_ = loop;

    // 设置动画 [citation:3]
    spine::TrackEntry* entry = m_animationState->setAnimation(
        trackIndex,
        animationName.toStdString().c_str(),
        loop_
    );

    if (entry) {
        // 可以设置轨道的特定属性
        // entry->setMixDuration(0.3f);  // 设置混合时长
        // entry->setTimeScale(1.0f);     // 设置播放速度
    }
    return entry != nullptr;  // 返回是否成功
}

void QtSkeletonLoader::initializeGL() {
    initializeOpenGLFunctions();

    // 创建简单的2D着色器
    shaderProgram = new QOpenGLShaderProgram(this);
    shaderProgram->addShaderFromSourceCode(QOpenGLShader::Vertex,
        "#version 330 core\n"
        "layout(location = 0) in vec2 a_position;\n"
        "layout(location = 1) in vec2 a_texCoord;\n"
        "layout(location = 2) in vec4 a_color;\n"
        "uniform mat4 u_proj;\n"
        "out vec2 v_texCoord;\n"
        "out vec4 v_color;\n"
        "void main() {\n"
        "    gl_Position = u_proj * vec4(a_position, 0.0, 1.0);\n"
        "    v_texCoord = a_texCoord;\n"
        "    v_color = a_color;\n"
        "}");

    shaderProgram->addShaderFromSourceCode(QOpenGLShader::Fragment,
        "#version 330 core\n"
        "in vec2 v_texCoord;\n"
        "in vec4 v_color;\n"
        "uniform sampler2D u_texture;\n"
        "out vec4 fragColor;\n"
        "void main() {\n"
        "    vec4 texColor = texture(u_texture, v_texCoord);\n"
        "    fragColor = texColor * v_color;\n"
        "}");

    shaderProgram->link();

    // 初始化VAO/VBO
    vao.create();
    vao.bind();

    vbo.create();
    vbo.bind();
    vbo.setUsagePattern(QOpenGLBuffer::DynamicDraw);

    ibo.create();
    ibo.bind();
    ibo.setUsagePattern(QOpenGLBuffer::DynamicDraw);

    // 设置顶点属性
    shaderProgram->enableAttributeArray(0); // position
    shaderProgram->setAttributeBuffer(0, GL_FLOAT, 0, 2, 8 * sizeof(float));

    shaderProgram->enableAttributeArray(1); // texCoord
    shaderProgram->setAttributeBuffer(1, GL_FLOAT, 2 * sizeof(float), 2, 8 * sizeof(float));

    shaderProgram->enableAttributeArray(2); // color
    shaderProgram->setAttributeBuffer(2, GL_FLOAT, 4 * sizeof(float), 4, 8 * sizeof(float));

    vao.release();

    // 启用混合
    glEnable(GL_BLEND);
}

void QtSkeletonLoader::testOpenGLRendering() {
    qDebug() << "=== OpenGL Rendering Test ===";

    // 测试1：检查着色器程序
    if (!shaderProgram || !shaderProgram->isLinked()) {
        qCritical() << "Shader program not valid";
        return;
    }

    // 测试2：检查VAO/VBO状态
    if (!vao.isCreated() || !vbo.isCreated() || !ibo.isCreated()) {
        qCritical() << "Buffer objects not created";
        return;
    }

    // 测试3：绘制多个颜色的矩形来验证颜色和位置
    struct TestVertex {
        float x, y;     // 位置
        float u, v;     // 纹理坐标
        float r, g, b, a; // 颜色
    };

    QVector<TestVertex> allVertices;
    QVector<GLushort> allIndices;

    // 矩形1：红色，左上角
    GLushort baseIndex = 0;
    allVertices.append({ 0, 0, 0, 0, 1, 0, 0, 1 });
    allVertices.append({ 100, 0, 0, 0, 1, 0, 0, 1 });
    allVertices.append({ 100, 100, 0, 0, 1, 0, 0, 1 });
    allVertices.append({ 0, 100, 0, 0, 1, 0, 0, 1 });

    // 使用显式类型转换
    allIndices.append(baseIndex);
    allIndices.append(baseIndex + 1);
    allIndices.append(baseIndex + 2);
    allIndices.append(baseIndex);
    allIndices.append(baseIndex + 2);
    allIndices.append(baseIndex + 3);

    // 矩形2：绿色，中心
    baseIndex = static_cast<GLushort>(allVertices.size());  // 4
    int cx = width() / 2 - 50;
    int cy = height() / 2 - 50;
    allVertices.append({ static_cast<float>(cx), static_cast<float>(cy), 0, 0, 0, 1, 0, 1 });
    allVertices.append({ static_cast<float>(cx + 100), static_cast<float>(cy), 0, 0, 0, 1, 0, 1 });
    allVertices.append({ static_cast<float>(cx + 100), static_cast<float>(cy + 100), 0, 0, 0, 1, 0, 1 });
    allVertices.append({ static_cast<float>(cx), static_cast<float>(cy + 100), 0, 0, 0, 1, 0, 1 });

    allIndices.append(baseIndex);
    allIndices.append(baseIndex + 1);
    allIndices.append(baseIndex + 2);
    allIndices.append(baseIndex);
    allIndices.append(baseIndex + 2);
    allIndices.append(baseIndex + 3);

    // 矩形3：蓝色，右下角
    baseIndex = static_cast<GLushort>(allVertices.size());  // 8
    allVertices.append({ static_cast<float>(width() - 100), static_cast<float>(height() - 100), 0, 0, 0, 0, 1, 1 });
    allVertices.append({ static_cast<float>(width()), static_cast<float>(height() - 100), 0, 0, 0, 0, 1, 1 });
    allVertices.append({ static_cast<float>(width()), static_cast<float>(height()), 0, 0, 0, 0, 1, 1 });
    allVertices.append({ static_cast<float>(width() - 100), static_cast<float>(height()), 0, 0, 0, 0, 1, 1 });

    allIndices.append(baseIndex);
    allIndices.append(baseIndex + 1);
    allIndices.append(baseIndex + 2);
    allIndices.append(baseIndex);
    allIndices.append(baseIndex + 2);
    allIndices.append(baseIndex + 3);

    qDebug() << "Test data prepared:"
        << allVertices.size() << "vertices,"
        << allIndices.size() << "indices";

    // 上传所有数据并绘制
    shaderProgram->bind();

    QMatrix4x4 proj;
    proj.ortho(0, width(), height(), 0, -1, 1);
    shaderProgram->setUniformValue("u_proj", proj);
    shaderProgram->setUniformValue("u_texture", 0);

    vao.bind();

    vbo.bind();
    vbo.allocate(allVertices.constData(), allVertices.size() * sizeof(TestVertex));

    ibo.bind();
    ibo.allocate(allIndices.constData(), allIndices.size() * sizeof(GLushort));

    // 设置属性指针
    shaderProgram->enableAttributeArray(0); // position
    shaderProgram->setAttributeBuffer(0, GL_FLOAT, offsetof(TestVertex, x), 2, sizeof(TestVertex));

    shaderProgram->enableAttributeArray(1); // texCoord
    shaderProgram->setAttributeBuffer(1, GL_FLOAT, offsetof(TestVertex, u), 2, sizeof(TestVertex));

    shaderProgram->enableAttributeArray(2); // color
    shaderProgram->setAttributeBuffer(2, GL_FLOAT, offsetof(TestVertex, r), 4, sizeof(TestVertex));

    // 验证属性位置
    qDebug() << "Attribute locations:"
        << "position:" << shaderProgram->attributeLocation("a_position")
        << "texCoord:" << shaderProgram->attributeLocation("a_texCoord")
        << "color:" << shaderProgram->attributeLocation("a_color");

    glBindTexture(GL_TEXTURE_2D, 0);
    glDrawElements(GL_TRIANGLES, allIndices.size(), GL_UNSIGNED_SHORT, nullptr);

    GLenum err = glGetError();
    if (err == GL_NO_ERROR) {
        qDebug() << "Test rendering successful";
        qDebug() << "Should see: Red(左上), Green(中心), Blue(右下)";
    }
    else {
        qCritical() << "Test rendering failed with error:" << err;
    }

    vao.release();
    shaderProgram->release();
}

void QtSkeletonLoader::paintGL() {

    glClearColor(0.2f, 0.2f, 0.2f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // ------------------------------------------------------------------
    glClearColor(0, 0, 1, 1);
    glClear(GL_COLOR_BUFFER_BIT);

    // 最简单的测试：一个红色的矩形
    struct Vertex {
        float x, y, u, v, r, g, b, a;
    };

    Vertex vertices[] = {
        {100, 100, 0, 0, 1, 0, 0, 1},  // 红色
        {300, 100, 0, 0, 1, 0, 0, 1},
        {300, 300, 0, 0, 1, 0, 0, 1},
        {100, 300, 0, 0, 1, 0, 0, 1}
    };

    GLushort indices[] = { 0, 1, 2, 0, 2, 3 };

    shaderProgram->bind();

    QMatrix4x4 proj;
    proj.ortho(0, width(), height(), 0, -1, 1);
    shaderProgram->setUniformValue("u_proj", proj);

    vao.bind();

    vbo.bind();
    vbo.allocate(vertices, sizeof(vertices));

    ibo.bind();
    ibo.allocate(indices, sizeof(indices));

    // 设置属性
    shaderProgram->enableAttributeArray(0);
    shaderProgram->setAttributeBuffer(0, GL_FLOAT, 0, 2, sizeof(Vertex));

    shaderProgram->enableAttributeArray(1);
    shaderProgram->setAttributeBuffer(1, GL_FLOAT, 2 * sizeof(float), 2, sizeof(Vertex));

    shaderProgram->enableAttributeArray(2);
    shaderProgram->setAttributeBuffer(2, GL_FLOAT, 4 * sizeof(float), 4, sizeof(Vertex));

    glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_SHORT, nullptr);

    vao.release();
    shaderProgram->release();
    // ------------------------------------------------------------------------

    if (!m_skeleton || !m_animationState) return;

    // 计算时间差
    static int lastTime = 0;
    int currentTime = clock();
    float deltaTime = (currentTime - lastTime) / 1000.0f;
    lastTime = currentTime;

    // 更新动画
    m_animationState->update(deltaTime);
    m_animationState->apply(*m_skeleton);
    m_skeleton->update(deltaTime);
    m_skeleton->updateWorldTransform(spine::Physics_Update);

    // 设置投影矩阵
    //QMatrix4x4 proj;
    proj.ortho(0, width(), height(), 0, -1, 1); // 注意Y轴翻转

    shaderProgram->bind();
    shaderProgram->setUniformValue("u_proj", proj);

    // 渲染骨架
    renderSkeleton(m_skeleton);

    shaderProgram->release();
}

void QtSkeletonLoader::renderSkeleton(spine::Skeleton* skeleton) {
    // 清空缓冲区
    vertexBuffer.clear();
    indexBuffer.clear();
    currentTexture = 0;
    currentBlendMode = spine::BlendMode_Normal;

    // 获取绘制顺序
    spine::Vector<spine::Slot*>& drawOrder = skeleton->getDrawOrder();

    // 遍历所有插槽
    for (size_t i = 0; i < drawOrder.size(); ++i) {
        spine::Slot* slot = drawOrder[i];
        spine::Attachment* attachment = slot->getAttachment();

        if (!attachment) continue;

        // 根据附件类型渲染
        if (attachment->getRTTI().isExactly(spine::RegionAttachment::rtti)) {
            renderRegionAttachment(slot, static_cast<spine::RegionAttachment*>(attachment));
        }
        else if (attachment->getRTTI().isExactly(spine::MeshAttachment::rtti)) {
            renderMeshAttachment(slot, static_cast<spine::MeshAttachment*>(attachment));
        }
    }

    // 刷新最后一帧
    flush();
}

void QtSkeletonLoader::renderRegionAttachment(spine::Slot* slot, spine::RegionAttachment* attachment) {
    // 获取AtlasRegion
    spine::TextureRegion* textureRegion = attachment->getRegion();
    spine::AtlasRegion* region = dynamic_cast<spine::AtlasRegion*>(textureRegion);
    if (!region || !region->page) return;

    // 从AtlasPage获取我们之前设置的纹理对象
    auto* texture = static_cast<QOpenGLTexture*>(region->page->texture);
    if (!texture) return;

    GLuint textureId = texture->textureId();
    spine::BlendMode blendMode = slot->getData().getBlendMode();

    // 如果纹理或混合模式变化，刷新当前批次
    if (textureId != currentTexture || blendMode != currentBlendMode) {
        flush();
        currentTexture = textureId;
        currentBlendMode = blendMode;
        setupBlendMode(blendMode);
    }

    // 计算世界坐标顶点
    float worldVertices[8];
    attachment->computeWorldVertices(*slot, worldVertices, 0, 8);

    // 获取UV坐标 - RegionAttachment有getUVs()方法
    spine::Vector<float>& uvs = attachment->getUVs();

    // 计算颜色 - 手动乘法
    spine::Color skeletonColor = m_skeleton->getColor();
    spine::Color slotColor = slot->getColor();
    spine::Color attachmentColor = attachment->getColor();

    // 手动进行颜色乘法
    spine::Color finalColor;
    finalColor.r = skeletonColor.r * slotColor.r * attachmentColor.r;
    finalColor.g = skeletonColor.g * slotColor.g * attachmentColor.g;
    finalColor.b = skeletonColor.b * slotColor.b * attachmentColor.b;
    finalColor.a = skeletonColor.a * slotColor.a * attachmentColor.a;

    // RegionAttachment是4个顶点的四边形
    int baseVertex = vertexBuffer.size() / 8; // 每个顶点8个float

    // 添加4个顶点
    for (int i = 0; i < 4; ++i) {
        // position (2 floats)
        vertexBuffer.append(worldVertices[i * 2]);
        vertexBuffer.append(worldVertices[i * 2 + 1]);

        // texCoord (2 floats)
        vertexBuffer.append(uvs[i * 2]);
        vertexBuffer.append(uvs[i * 2 + 1]);

        // color (4 floats)
        vertexBuffer.append(finalColor.r);
        vertexBuffer.append(finalColor.g);
        vertexBuffer.append(finalColor.b);
        vertexBuffer.append(finalColor.a);
    }

    // 添加索引（两个三角形：0-1-2 和 0-2-3）
    indexBuffer.append(baseVertex);
    indexBuffer.append(baseVertex + 1);
    indexBuffer.append(baseVertex + 2);
    indexBuffer.append(baseVertex);
    indexBuffer.append(baseVertex + 2);
    indexBuffer.append(baseVertex + 3);
}

void QtSkeletonLoader::renderMeshAttachment(spine::Slot* slot, spine::MeshAttachment* attachment) {
    // MeshAttachment同样通过getRendererObject()返回AtlasRegion
    spine::TextureRegion* textureRegion = attachment->getRegion();
    spine::AtlasRegion* region = dynamic_cast<spine::AtlasRegion*>(textureRegion);
    if (!region || !region->page) return;

    auto* texture = static_cast<QOpenGLTexture*>(region->page->texture);
    if (!texture) return;

    GLuint textureId = texture->textureId();
    spine::BlendMode blendMode = slot->getData().getBlendMode();

    // 如果纹理或混合模式变化，刷新当前批次
    if (textureId != currentTexture || blendMode != currentBlendMode) {
        flush();
        currentTexture = textureId;
        currentBlendMode = blendMode;
        setupBlendMode(blendMode);
    }

    // 获取世界坐标 - 使用computeWorldVertices计算
    int numVertices = attachment->getWorldVerticesLength() / 2;
    spine::Vector<float> worldVertices;
    worldVertices.setSize(attachment->getWorldVerticesLength(), 1.0);
    attachment->computeWorldVertices(*slot, 0, 1, worldVertices, 0, attachment->getWorldVerticesLength());

    // 获取UVs - MeshAttachment有getUVs()方法
    spine::Vector<float>& uvs = attachment->getUVs();

    // 获取三角形索引
    spine::Vector<unsigned short>& triangles = attachment->getTriangles();

    // 计算颜色
    spine::Color skeletonColor = m_skeleton->getColor();
    spine::Color slotColor = slot->getColor();
    spine::Color attachmentColor = attachment->getColor();

    spine::Color finalColor;
    finalColor.r = skeletonColor.r * slotColor.r * attachmentColor.r;
    finalColor.g = skeletonColor.g * slotColor.g * attachmentColor.g;
    finalColor.b = skeletonColor.b * slotColor.b * attachmentColor.b;
    finalColor.a = skeletonColor.a * slotColor.a * attachmentColor.a;

    int baseVertex = vertexBuffer.size() / 8;

    // 添加所有顶点
    for (int i = 0; i < numVertices; ++i) {
        // position (2 floats)
        vertexBuffer.append(worldVertices[i * 2]);
        vertexBuffer.append(worldVertices[i * 2 + 1]);

        // texCoord (2 floats)
        vertexBuffer.append(uvs[i * 2]);
        vertexBuffer.append(uvs[i * 2 + 1]);

        // color (4 floats)
        vertexBuffer.append(finalColor.r);
        vertexBuffer.append(finalColor.g);
        vertexBuffer.append(finalColor.b);
        vertexBuffer.append(finalColor.a);
    }

    // 添加索引（需要加上baseVertex偏移）
    for (int i = 0; i < triangles.size(); ++i) {
        indexBuffer.append(baseVertex + triangles[i]);
    }
}

void QtSkeletonLoader::flush() {
    if (vertexBuffer.isEmpty() || indexBuffer.isEmpty()) return;

    // 绑定VAO
    vao.bind();

    // 上传顶点数据
    vbo.bind();
    vbo.allocate(vertexBuffer.constData(), vertexBuffer.size() * sizeof(float));

    // 上传索引数据
    ibo.bind();
    ibo.allocate(indexBuffer.constData(), indexBuffer.size() * sizeof(GLushort));

    // 绑定纹理
    glBindTexture(GL_TEXTURE_2D, currentTexture);

    // 绘制
    glDrawElements(GL_TRIANGLES, indexBuffer.size(), GL_UNSIGNED_SHORT, nullptr);

    // 解绑
    vao.release();

    // 清空缓冲区，准备下一个批次
    vertexBuffer.clear();
    indexBuffer.clear();
}

void QtSkeletonLoader::setupBlendMode(spine::BlendMode blendMode) {
    switch (blendMode) {
    case spine::BlendMode_Normal:
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        break;
    case spine::BlendMode_Additive:
        glBlendFunc(GL_SRC_ALPHA, GL_ONE);
        break;
    case spine::BlendMode_Multiply:
        glBlendFunc(GL_DST_COLOR, GL_ONE_MINUS_SRC_ALPHA);
        break;
    case spine::BlendMode_Screen:
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_COLOR);
        break;
    default:
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        break;
    }
}
