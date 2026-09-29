/*
 * AronaArchive - 自循环 AI
 * Copyright (C) 2026 xia_hy456
 *
 * @Author: xia_hy456
 * @Date: 2026/3/14 22:15:53
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 * SPDX-License-Identifier: GPL-3.0-or-later
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