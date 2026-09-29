/*
 * AronaArchive - 自循环 AI
 * Copyright (C) 2026 xia_hy456
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