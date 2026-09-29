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


#ifndef SPINE_QTTEXTURELOADER_H
#define SPINE_QTTEXTURELOADER_H

#include <Defines.h>

#include <spine/TextureLoader.h>
#include <spine/Atlas.h>
#include <QOpenGLWidget>
#include <QOpenGLFunctions>
#include <QOpenGLShaderProgram>
#include <QOpenGLBuffer>
#include <QOpenGLVertexArrayObject>
#include <QOpenGLTexture>
#include <QOpenGLContext>
#include <QDebug>
#include <QImage>
#include <unordered_map>

class QtTextureLoader : public spine::TextureLoader {
public:
    virtual void load(spine::AtlasPage& page, const spine::String& path) override;
    virtual void unload(void* texture) override;

private:
    std::unordered_map<GLuint, QOpenGLTexture*> m_textureMap;
};

#endif // SPINE_QTTEXTURELOADER_H