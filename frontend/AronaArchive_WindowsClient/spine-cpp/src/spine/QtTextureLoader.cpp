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

#include <spine/QtTextureLoader.h>

void QtTextureLoader::load(spine::AtlasPage& page, const spine::String& path) {
    std::string pathStr(path.buffer());
    QString qImgPath = QString::fromStdString(pathStr);

    // 使用QImage加载图片
    QImage image;
    if (!image.load(qImgPath)) {
        ERROR_DEBUG_OUTPUT("[Spine Operation] Texture Load Failed! Texture: " + qImgPath);
        return;
    }

    FINE_DEBUG_OUTPUT(QString("[Spine Operation]Original image format:") //+ image.format()
        + "Size:" + QString::number(image.width()) + "x" + QString::number(image.height())
        + "Has Alpha:" + QString(image.hasAlphaChannel()?"true":"false"));

    // 确保图片是RGBA格式
    if (image.format() != QImage::Format_RGBA8888) {
        image = image.convertToFormat(QImage::Format_RGBA8888);
    }

    // 创建OpenGL纹理
    QOpenGLTexture* glTexture = new QOpenGLTexture(image.mirrored());
    glTexture->setMinificationFilter(QOpenGLTexture::Linear);
    glTexture->setMagnificationFilter(QOpenGLTexture::Linear);
    glTexture->setWrapMode(QOpenGLTexture::ClampToEdge);

    // 获取纹理ID
    GLuint textureId = glTexture->textureId();

    // 存储纹理ID到page.texture
    GLuint* textureIdPtr = new GLuint(textureId);
    page.texture = textureIdPtr;

    // 同时也存储QOpenGLTexture指针以便正确释放
    m_textureMap[textureId] = glTexture;

    // 设置大图的实际像素宽高
    page.width = image.width();
    page.height = image.height();

    FINE_DEBUG_OUTPUT(QString("[Spine Operation] Texture Load Succeed! ")
        + " Path: " + qImgPath
        + "| Size: " + QString::number(page.width) + "x" + QString::number(page.height)
        + "| Texture ID: " + QString::number(textureId));
}

void QtTextureLoader::unload(void* texture) {
    GLuint* textureIdPtr = static_cast<GLuint*>(texture);
    if (textureIdPtr) {
        GLuint textureId = *textureIdPtr;

        // 查找并删除QOpenGLTexture对象
        auto it = m_textureMap.find(textureId);
        if (it != m_textureMap.end()) {
            delete it->second;  // QOpenGLTexture析构函数会自动调用glDeleteTextures
            m_textureMap.erase(it);
        }

        // 删除纹理ID指针
        delete textureIdPtr;
    }
    FINE_DEBUG_OUTPUT("[Spine Operation] Texture Unload Succeed! ");
}