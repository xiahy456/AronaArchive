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