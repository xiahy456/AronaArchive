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

#include "BlueakaFontLoader.h"
#include <QFontDatabase>
#include <QDir>
#include <QDebug>
#include <QApplication>
#include <QFileInfo>

BlueakaFontLoader* BlueakaFontLoader::m_instance = nullptr;

BlueakaFontLoader* BlueakaFontLoader::instance()
{
    if (!m_instance) {
        m_instance = new BlueakaFontLoader(qApp);
    }
    return m_instance;
}

BlueakaFontLoader::BlueakaFontLoader(QObject* parent)
    : QObject(parent)
{
}

BlueakaFontLoader::~BlueakaFontLoader()
{
}

bool BlueakaFontLoader::loadFromDirectory(const QString& directory)
{
    QDir fontDir(directory);
    if (!fontDir.exists()) {
        ERROR_DEBUG_OUTPUT("[Font Loader]Font directory not found:" + directory);
        return false;
    }

    // 获取所有 TTF 文件
    QStringList filters;
    filters << "*.ttf" << "*.otf";
    QFileInfoList fontFiles = fontDir.entryInfoList(filters, QDir::Files);

    if (fontFiles.isEmpty()) {
        ERROR_DEBUG_OUTPUT("[Font Loader]No TTF/OTF files found in:" + directory);
        return false;
    }

    FINE_DEBUG_OUTPUT("[Font Loader]Found" + QString::number(fontFiles.size()) + "font files");

    QFontDatabase fontDb;
    int loadedCount = 0;

    for (const QFileInfo& fontFile : fontFiles) {
        QString fontPath = fontFile.absoluteFilePath();
        int fontId = fontDb.addApplicationFont(fontPath);

        if (fontId != -1) {
            loadedCount++;
            m_loadedFiles << fontPath;

            // 获取字体族名称
            QStringList families = fontDb.applicationFontFamilies(fontId);
            for (const QString& family : families) {
                if (!m_fontFamilies.contains(family)) {
                    m_fontFamilies << family;
                }
            }

            FINE_DEBUG_OUTPUT("[Font Loader]Head loaded:" + fontFile.fileName() + "->" + families[0]);
        }
        else {
            ERROR_DEBUG_OUTPUT("[Font Loader]Failed:" + fontFile.fileName());
        }
    }

    FINE_DEBUG_OUTPUT("[Font Loader]Total loaded:" + QString::number(loadedCount) + "fonts");
    FINE_DEBUG_OUTPUT("[Font Loader]Font families:" + m_fontFamilies[0]);

    return !m_fontFamilies.isEmpty();
}

bool BlueakaFontLoader::loadFromResource(const QString& resourcePath)
{
    QDir fontDir(resourcePath);
    return loadFromDirectory(resourcePath);
}

QFont BlueakaFontLoader::createFont(int pointSize, bool bold, bool italic)
{
    if (m_fontFamilies.isEmpty()) {
        ERROR_DEBUG_OUTPUT("[Font Loader]No Blueaka font loaded, using default font");
        return QFont();
    }

    QFont font;
    font.setFamily(m_fontFamilies.first());
    font.setPointSize(pointSize);
    font.setBold(bold);
    font.setItalic(italic);

    return font;
}

QFont BlueakaFontLoader::createFont(int pointSize, QFont::Weight weight, bool italic)
{
    if (m_fontFamilies.isEmpty()) {
        ERROR_DEBUG_OUTPUT("[Font Loader]No Blueaka font loaded, using default font");
        return QFont();
    }

    QFont font;
    font.setFamily(m_fontFamilies.first());
    font.setPointSize(pointSize);
    font.setWeight(weight);
    font.setItalic(italic);

    return font;
}