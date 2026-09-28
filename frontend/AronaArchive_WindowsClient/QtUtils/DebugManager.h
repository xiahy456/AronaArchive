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
