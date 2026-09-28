/*
 Copyright 2026 xia_hy456. All rights reserved.

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

#ifndef BLUEAKAFONTLOADER_H
#define BLUEAKAFONTLOADER_H

#include <QObject>
#include <QFont>
#include <QStringList>
#include <QMap>
#include <QFontInfo>
#include <QFontMetrics>

#include <Defines.h>

class BlueakaFontLoader : public QObject
{
    Q_OBJECT

public:
    static BlueakaFontLoader* instance();

    // 从目录加载所有 TTF 文件
    bool loadFromDirectory(const QString& directory);

    // 从资源文件加载
    bool loadFromResource(const QString& resourcePath);

    // 检查字体是否已加载
    bool isLoaded() const { return !m_fontFamilies.isEmpty(); }

    // 获取字体族名称列表
    QStringList getFontFamilies() const { return m_fontFamilies; }

    // 创建字体对象（简化版）
    QFont createFont(int pointSize = 12, bool bold = false, bool italic = false);

    // 创建字体对象（高级版）
    QFont createFont(int pointSize, QFont::Weight weight, bool italic = false);

    // 获取主字体族名称
    QString getMainFontFamily() const { return m_fontFamilies.isEmpty() ? "" : m_fontFamilies.first(); }

private:
    explicit BlueakaFontLoader(QObject* parent = nullptr);
    ~BlueakaFontLoader();

    static BlueakaFontLoader* m_instance;
    QStringList m_fontFamilies;
    QStringList m_loadedFiles;
};

#endif // BLUEAKAFONTLOADER_H