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

#include "SpokenTextSplitter.h"

#include <QtGlobal>

namespace SpokenTextSplitter {
namespace {

const QChar kIdeographicFullStop(0x3002);   // 。
const QChar kFullwidthQuestion(0xFF1F);     // ？
const QChar kFullwidthExclamation(0xFF01);  // ！
const QChar kHorizontalEllipsis(0x2026);    // …
const QChar kFullwidthComma(0xFF0C);        // ，
const QChar kIdeographicComma(0x3001);      // 、

int matchTerminalDelim(const QString& s, int i)
{
    if (i < 0 || i >= s.size()) {
        return 0;
    }
    if (i + 1 < s.size()
        && s.at(i) == kHorizontalEllipsis
        && s.at(i + 1) == kHorizontalEllipsis) {
        return 2;
    }
    const QChar c = s.at(i);
    if (c == kIdeographicFullStop
        || c == kFullwidthQuestion
        || c == kFullwidthExclamation
        || c == QLatin1Char('?')
        || c == QLatin1Char('!')) {
        return 1;
    }
    return 0;
}

int matchClauseDelim(const QString& s, int i)
{
    if (i < 0 || i >= s.size()) {
        return 0;
    }
    if (i + 1 < s.size()
        && s.at(i) == kHorizontalEllipsis
        && s.at(i + 1) == kHorizontalEllipsis) {
        return 0;
    }
    const QChar c = s.at(i);
    if (c == kFullwidthComma || c == kIdeographicComma || c == kHorizontalEllipsis) {
        return 1;
    }
    return 0;
}

QStringList splitByTerminal(const QString& text)
{
    QStringList parts;
    int start = 0;
    for (int i = 0; i < text.size(); ) {
        const int n = matchTerminalDelim(text, i);
        if (n > 0) {
            parts.append(text.mid(start, i + n - start));
            i += n;
            start = i;
            continue;
        }
        ++i;
    }
    if (start < text.size()) {
        parts.append(text.mid(start));
    }
    return parts;
}

int lastClauseCutAtMost(const QString& s, int maxLen)
{
    int cut = -1;
    const int limit = qMin(maxLen, s.size());
    for (int i = 0; i < limit; ) {
        if (i + 1 < s.size()
            && s.at(i) == kHorizontalEllipsis
            && s.at(i + 1) == kHorizontalEllipsis) {
            i += 2;
            continue;
        }
        const int n = matchClauseDelim(s, i);
        if (n > 0) {
            const int end = i + n;
            if (end <= maxLen) {
                cut = end;
            }
            i += n;
            continue;
        }
        ++i;
    }
    return cut;
}

QStringList binarySplitByClause(const QString& s)
{
    if (s.isEmpty()) {
        return {};
    }
    if (s.size() <= kMaxSpokenSegmentChars) {
        return {s};
    }

    const int cut = lastClauseCutAtMost(s, kMaxSpokenSegmentChars);
    const int splitAt = (cut > 0) ? cut : kMaxSpokenSegmentChars;
    const QString left = s.left(splitAt).trimmed();
    const QString right = s.mid(splitAt).trimmed();

    QStringList out;
    if (!left.isEmpty()) {
        out.append(left);
    }
    if (!right.isEmpty()) {
        out.append(binarySplitByClause(right));
    }
    return out;
}

} // namespace

QStringList split(const QString& text)
{
    const QString t = text.trimmed();
    if (t.isEmpty()) {
        return {};
    }
    if (t.size() <= kMaxSpokenSegmentChars) {
        return {t};
    }

    QStringList messages;
    QString current;
    const QStringList sentences = splitByTerminal(t);
    for (const QString& raw : sentences) {
        const QString s = raw.trimmed();
        if (s.isEmpty()) {
            continue;
        }
        if (s.size() > kMaxSpokenSegmentChars) {
            if (!current.isEmpty()) {
                messages.append(current);
                current.clear();
            }
            messages.append(binarySplitByClause(s));
            continue;
        }
        if (current.size() + s.size() <= kMaxSpokenSegmentChars) {
            current += s;
        } else {
            if (!current.isEmpty()) {
                messages.append(current);
            }
            current = s;
        }
    }
    if (!current.isEmpty()) {
        messages.append(current);
    }
    return messages;
}

} // namespace SpokenTextSplitter
