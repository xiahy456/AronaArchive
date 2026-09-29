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

#include <QObject>
#include <QDateTime>
#include <QTime>
#include <QFile>

class DebugManager  : public QObject
{
	Q_OBJECT

public:
    static DebugManager* instance();

    // 发送调试消息
    void sendDebugMessage(const QString& message, const QString& sender = "");

    // 获取缓存的调试信息
    void flushPendingMessages();

signals:
    // 调试消息信号
    void debugMessageReceived(const QString& message);

private:
    explicit DebugManager(QObject* parent = nullptr);
    ~DebugManager() override;

    bool ensureLogFile();
    void appendToLogFile(const QString& formattedMsg);

    static DebugManager* m_instance;
    QStringList m_pendingMessages;  // 缓存未发送的消息

    QFile m_logFile;
    QString m_logDate;
    bool m_logOpenFailed = false;
};
