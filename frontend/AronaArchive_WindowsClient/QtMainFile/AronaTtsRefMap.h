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


#pragma once

#include "Defines.h"
#include "GlobalVariables.h"
#include "JsonOperation.h"

#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>

namespace AronaTtsRef {

struct TtsRef {
    QString refAudioPath;
    QString promptText;
};

/** emotion -> {ref_audio_path, prompt_text} loaded from tts.refs; no hardcoded keys. */
class Map {
public:
    void loadFromConfig()
    {
        m_byEmotion.clear();
        m_fallback = TtsRef();
        if (_global_config == nullptr) {
            return;
        }

        JsonOperation tts = _global_config->getJson(QStringLiteral("tts"));
        m_fallback.refAudioPath = tts.getString(QStringLiteral("ref_audio_path"));
        m_fallback.promptText = tts.getString(QStringLiteral("prompt_text"));

        const QJsonArray refs = tts.m_jsonObj.value(QStringLiteral("refs")).toArray();
        for (const QJsonValue& value : refs) {
            if (!value.isObject()) {
                continue;
            }
            const QJsonObject obj = value.toObject();
            const QString emotion = obj.value(QStringLiteral("emotion")).toString().trimmed().toLower();
            const QString path = obj.value(QStringLiteral("ref_audio_path")).toString().trimmed();
            if (emotion.isEmpty() || path.isEmpty()) {
                continue;
            }
            TtsRef entry;
            entry.refAudioPath = path;
            entry.promptText = obj.value(QStringLiteral("prompt_text")).toString();
            m_byEmotion.insert(emotion, entry);
        }

        FINE_DEBUG_OUTPUT(QString("[TTS] Loaded %1 emotion ref(s) from tts.refs")
            .arg(m_byEmotion.size()));
    }

    TtsRef resolve(const QString& emotion) const
    {
        const QString key = emotion.trimmed().toLower();
        if (key.isEmpty()) {
            return m_fallback;
        }
        const auto it = m_byEmotion.constFind(key);
        if (it == m_byEmotion.cend() || it->refAudioPath.isEmpty()) {
            return m_fallback;
        }
        return *it;
    }

private:
    QHash<QString, TtsRef> m_byEmotion;
    TtsRef m_fallback;
};

}  // namespace AronaTtsRef
