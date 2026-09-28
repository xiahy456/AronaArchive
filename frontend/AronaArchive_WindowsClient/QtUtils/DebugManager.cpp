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

#include "DebugManager.h"

#include <QDate>
#include <QDir>
#include <QDebug>

DebugManager* DebugManager::m_instance = nullptr;

DebugManager* DebugManager::instance()
{
    if (!m_instance) {
        m_instance = new DebugManager();
    }
    return m_instance;
}

DebugManager::DebugManager(QObject* parent) : QObject(parent)
{
}

DebugManager::~DebugManager()
{
    if (m_logFile.isOpen()) {
        m_logFile.flush();
        m_logFile.close();
    }
}

bool DebugManager::ensureLogFile()
{
    if (m_logOpenFailed) {
        return false;
    }

    const QString today = QDate::currentDate().toString("yyyy-MM-dd");
    if (m_logFile.isOpen() && m_logDate == today) {
        return true;
    }

    if (m_logFile.isOpen()) {
        m_logFile.flush();
        m_logFile.close();
    }

    if (!QDir().mkpath("logs")) {
        m_logOpenFailed = true;
        qWarning().noquote() << "Failed to create logs directory";
        return false;
    }

    const QString logPath = QString("logs/arona-%1.log").arg(today);
    m_logFile.setFileName(logPath);
    if (!m_logFile.open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text)) {
        m_logOpenFailed = true;
        qWarning().noquote() << "Failed to open log file:" << logPath << m_logFile.errorString();
        return false;
    }

    m_logDate = today;
    return true;
}

void DebugManager::appendToLogFile(const QString& formattedMsg)
{
    if (!ensureLogFile()) {
        return;
    }

    m_logFile.write(formattedMsg.toUtf8());
    m_logFile.write("\n");
    m_logFile.flush();
}

void DebugManager::sendDebugMessage(const QString& message, const QString& sender)
{
    QString formattedMsg;
    if (!sender.isEmpty()) {
        formattedMsg = QString("[%1][%2]%3").arg(sender).arg(QTime::currentTime().toString("hh:mm:ss")).arg(message);
    }
    else {
        formattedMsg = message;
    }

    appendToLogFile(formattedMsg);

    // 检查是否有接收者
    if (receivers(SIGNAL(debugMessageReceived(QString))) > 0) {
        emit debugMessageReceived(formattedMsg);
    }
    else {
        m_pendingMessages.append(formattedMsg);  // 缓存
    }
}

void DebugManager::flushPendingMessages()
{
    for (const QString& msg : m_pendingMessages) {
        emit debugMessageReceived(msg);
    }
    m_pendingMessages.clear();
}
