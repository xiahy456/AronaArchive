#ifndef QTSKELETONLOAD_H
#define QTSKELETONLOAD_H

#include <QDebug>
#include <QString>
#include <QOpenGLTexture>
#include <QOpenGLWidget>
#include <QOpenGLShaderProgram>
#include <QOpenGLVertexArrayObject>
#include <QOpenGLBuffer>
#include <QOpenGLFunctions_3_3_Core>

#include <string>
#include <memory>

#include "QtSpineExtension.h"
#include "QtTextureLoader.h"

#include "spine/Atlas.h"
#include "spine/SpineString.h"
#include "spine/AtlasAttachmentLoader.h"
#include "spine/SkeletonJson.h"
#include "spine/SkeletonData.h"
#include "spine/Skeleton.h"
#include "spine/AnimationState.h"
#include "spine/AnimationStateData.h"
#include "spine/Attachment.h"
#include "spine/RegionAttachment.h"
#include "spine/MeshAttachment.h"
#include "spine/BlendMode.h"
#include "spine/SlotData.h"
#include "spine/TextureRegion.h"

class QtSkeletonLoader : public QOpenGLWidget, protected QOpenGLFunctions_3_3_Core
{
public:
    QtSkeletonLoader(const std::string& atlasPath, const std::string& skeletonJsonPath);
    ~QtSkeletonLoader() {};
    bool PlayAnimation(const QString& animationName, bool loop = true);
    void testOpenGLRendering();

protected:
    bool Load();
	bool ModelCreate(const std::string& atlasPath, const std::string& skeletonJsonPath);
    void initializeGL() override;
    void paintGL() override;
    //void resizeGL(int w, int h) override;

private:
    std::unique_ptr<spine::Atlas> m_atlas;
    std::unique_ptr<spine::SkeletonData> m_skeletonData;
    spine::String m_atlasPath;
    spine::String m_skeletonJsonPath;
    QtTextureLoader m_QtTextureLoader;
	spine::Skeleton *m_skeleton;
	spine::AnimationStateData* m_animationStateData;
	spine::AnimationState* m_animationState;

    // OpenGL相关
    QOpenGLShaderProgram* shaderProgram = nullptr;
    QOpenGLVertexArrayObject vao;
    QOpenGLBuffer vbo{ QOpenGLBuffer::VertexBuffer };
    QOpenGLBuffer ibo{ QOpenGLBuffer::IndexBuffer };

    // 临时缓冲区（用于每帧上传顶点数据）
    QVector<float> vertexBuffer;
    QVector<GLushort> indexBuffer;

    // 渲染状态
    GLuint currentTexture = 0;
    spine::BlendMode currentBlendMode = spine::BlendMode_Normal;

    // 渲染函数
    void renderSkeleton(spine::Skeleton* skeleton);
    void renderRegionAttachment(spine::Slot* slot, spine::RegionAttachment* attachment);
    void renderMeshAttachment(spine::Slot* slot, spine::MeshAttachment* attachment);
    void flush(); // 刷新渲染批次
    void setupBlendMode(spine::BlendMode blendMode);
};

#endif // QTSKELETONLOAD_H