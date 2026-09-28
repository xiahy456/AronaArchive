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

#ifndef QTSPINEWIDGET_H
#define QTSPINEWIDGET_H

#include <spine/QtTextureLoader.h>

#include <GlobalInclude.h>

#include <QOpenGLWidget>
#include <QOpenGLFunctions>
#include <QOpenGLShaderProgram>
#include <QOpenGLBuffer>
#include <QOpenGLVertexArrayObject>
#include <QElapsedTimer>
#include <QVector>
#include <QOpenGLTexture>
#include <QOpenGLExtraFunctions>
#include <QFrame>
#include <QPoint>
#include <QPointF>
#include <QMouseEvent>
#include <QShowEvent>
#include <QHideEvent>
#include <QCoreApplication>
#include <QApplication>

#include <memory>
#include <vector>

namespace spine {
    class SkeletonData;
    class Skeleton;
    class AnimationStateData;
    class AnimationState;
    class Atlas;
    class SkeletonBinary;
    class SkeletonJson;
    class RegionAttachment;
    class MeshAttachment;
    class Slot;
    class Color;
    class Bone;
}

class QtSpineManager : public QOpenGLWidget, protected QOpenGLFunctions
{
    Q_OBJECT

public:
    struct SpineVertex {
        float x, y;        // 位置
        float u, v;        // 纹理坐标
        float r, g, b, a;  // 颜色
    };

    struct TextureBatch {
        GLuint textureId;
        bool premultiplied = false;
        QVector<SpineVertex> vertices;
    };

    explicit QtSpineManager(QWidget* parent = nullptr);
    ~QtSpineManager();

    bool isGLReady() const { return m_glReady; }

    void loadSpineFile(const QString& atlasPath, const QString& skelOrJsonPath);
    void setAnimation(const QString& name, int track_idx, bool loop = true);
	void clearAnimation(int track_idx, float mix_duration);

signals:
    void spineLoaded();
    void glReady();
    void patEnded(int durationMs);

protected:
    // 重写OpenGL相关函数
    void initializeGL() override;
    void paintGL() override;
    void resizeGL(int w, int h) override;
    void showEvent(QShowEvent* event) override;
    void hideEvent(QHideEvent* event) override;

    // 重写鼠标事件
    void mousePressEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;

private:
    void updateAnimation();
    GLuint getTextureId(spine::RegionAttachment* attachment);
    GLuint getTextureId(spine::MeshAttachment* attachment);
    bool getTexturePremultiplied(spine::RegionAttachment* attachment);
    bool getTexturePremultiplied(spine::MeshAttachment* attachment);
    void collectRegionAttachmentVertices(spine::RegionAttachment* attachment, spine::Slot* slot, const spine::Color& slotColor);
    void collectMeshAttachmentVertices(spine::MeshAttachment* attachment, spine::Slot* slot, const spine::Color& slotColor);
    TextureBatch* acquireBatch(GLuint textureId, bool premultiplied);
    void flushBatches();
    void requestNextFrame();
    void setAttachmentRelativeTransform(const QString& slotName, float offsetX, float offsetY, float rotation = 0.0f, float scaleX = 1.0f, float scaleY = 1.0f);

    void refreshSpineViewTransform();
    QPointF widgetToSpineWorld(const QPointF& widgetPos) const;
    bool isInPatHitBox(const QPointF& spineWorld) const;
    void updateMouseWorldFromWidget(const QPointF& widgetPos);
    void holdPatAnimation(int track_idx, const char* name);
    void playPatEndAnimation(int track_idx, const char* name);
    void handlePat();
    void handlePatEnd();
    float computePatFollowT() const;
    float stepPatFollowT(float target, float dt);
    void applyPatFollow(float t);
    void cachePatBones();
    void logPatAnimations();

    // Spine 对象
    spine::Atlas* m_atlas = nullptr;
    QtTextureLoader* m_textureLoader = nullptr;
    spine::SkeletonData* m_skeletonData = nullptr;
    spine::Skeleton* m_skeleton = nullptr;
    spine::AnimationStateData* m_animationStateData = nullptr;
    spine::AnimationState* m_animationState = nullptr;

    // 骨骼显示位置（与 paintGL 矩阵一致：origin + 视觉缩放，Y 翻转）
    float m_spineX = 0.0f;
    float m_spineY = 0.0f;
    float m_scale = 1.0f;

    // vsync 驱动的动画时钟（QElapsedTimer 只 start 一次）
    QElapsedTimer m_elapsedTimer;
    qint64 m_lastTimeNs = 0;
    bool m_renderLoopActive = true;

    float m_defaultMix = 0.2f;
    float m_cachedZoom = -1.0f;

    // 摸头状态
    bool m_leftDown = false;
    bool m_patActive = false;
    bool m_patEnding = false;
    float m_patFollowT = 0.0f;
    float m_patEndFromT = 0.0f;
    float m_patEndElapsed = 0.0f;
    QPointF m_mouseWorld;
    QElapsedTimer m_patPressTimer;

    spine::Bone* m_touchPointBone = nullptr;
    spine::Bone* m_touchPointKeyBone = nullptr;
    spine::Bone* m_headBone = nullptr;
    spine::Bone* m_patHitBone = nullptr;

    // OpenGL 资源
    QOpenGLShaderProgram* m_program = nullptr;
    QOpenGLBuffer* m_vbo = nullptr;
    QOpenGLVertexArrayObject* m_vao = nullptr;
    int m_vboAllocatedBytes = 0;
    bool m_glReady = false;

    // 统一变量位置
    GLint m_u_matrixLoc;
    GLint m_u_textureLoc;
    GLint m_u_premultipliedLoc;

    // 批次数据（跨帧复用 QVector 容量）
    QVector<TextureBatch> m_batches;
    int m_usedBatches = 0;
    std::vector<float> m_worldVertices;
};

#endif // QTSPINEWIDGET_H