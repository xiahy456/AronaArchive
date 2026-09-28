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

#pragma once

#include <QHash>
#include <QString>

namespace AronaEmotion {

inline const QHash<QString, QString>& englishToAnim()
{
    static const QHash<QString, QString> kMap = {
        {QStringLiteral("normal"), QStringLiteral("00")},
        {QStringLiteral("curious"), QStringLiteral("02")},
        {QStringLiteral("smile"), QStringLiteral("03")},
        {QStringLiteral("worried"), QStringLiteral("04")},
        {QStringLiteral("angry"), QStringLiteral("05")},
        {QStringLiteral("angry_shame"), QStringLiteral("06")},
        {QStringLiteral("disgusted"), QStringLiteral("07")},
        {QStringLiteral("disgusted_surprised"), QStringLiteral("08")},
        {QStringLiteral("disgusted_worried"), QStringLiteral("09")},
        {QStringLiteral("frustration"), QStringLiteral("10")},
        {QStringLiteral("like"), QStringLiteral("11")},
        {QStringLiteral("very_happy"), QStringLiteral("12")},
        {QStringLiteral("enjoy"), QStringLiteral("13")},
        {QStringLiteral("complaint"), QStringLiteral("14")},
        {QStringLiteral("unwilling"), QStringLiteral("15")},
        {QStringLiteral("shy"), QStringLiteral("16")},
        {QStringLiteral("shout"), QStringLiteral("20")},
        {QStringLiteral("want"), QStringLiteral("21")},
        {QStringLiteral("confident_serious"), QStringLiteral("22")},
        {QStringLiteral("sleep_very_content"), QStringLiteral("23")},
        {QStringLiteral("sleep_question"), QStringLiteral("24")},
        {QStringLiteral("confident"), QStringLiteral("25")},
        {QStringLiteral("disappointed"), QStringLiteral("26")},
        {QStringLiteral("disappointed_disgusted"), QStringLiteral("27")},
        {QStringLiteral("very_surprised"), QStringLiteral("28")},
        {QStringLiteral("dizzy"), QStringLiteral("29")},
        {QStringLiteral("surprise"), QStringLiteral("31")},
        {QStringLiteral("surprise_very_happy"), QStringLiteral("32")},
        {QStringLiteral("sleep"), QStringLiteral("99")},
    };
    return kMap;
}

/** Map backend emotion English value to Spine track-1 animation name. */
inline QString toAnimationName(const QString& emotionEnglish)
{
    const QString key = emotionEnglish.trimmed().toLower();
    const auto& map = englishToAnim();
    return map.value(key, QStringLiteral("00"));
}

/** Known emotion key, or "normal" when the string is not in the map. */
inline QString resolveOrNormal(const QString& emotionEnglish)
{
    const QString key = emotionEnglish.trimmed().toLower();
    if (englishToAnim().contains(key)) {
        return key;
    }
    return QStringLiteral("normal");
}

}  // namespace AronaEmotion
