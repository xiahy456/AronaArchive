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


#ifndef TENCENTSPEECHRECOGNIZER_H
#define TENCENTSPEECHRECOGNIZER_H

#include "Defines.h"

#include <QObject>
#include <QWebSocket>
#include <QTimer>
#include <QByteArray>
#include <QString>
#include <QAbstractSocket>

class TencentSpeechRecognizer : public QObject
{
    Q_OBJECT

public:
    explicit TencentSpeechRecognizer(QObject* parent = nullptr);
    ~TencentSpeechRecognizer();

    void setCredentials(const QString& secretId, const QString& secretKey, const QString& appId);
    void setVadSilenceTime(int ms);
    bool isInitialized() const;
    bool isStreaming() const;

    bool startRealtime();
    void stopRealtime();
    void sendAudio(const QByteArray& pcm);

signals:
    void errorOccurred(const QString& error);
    void transcriptReceived(const QString& text, bool isFinal, int sliceType);

private slots:
    void onConnected();
    void onDisconnected();
    void onTextMessage(const QString& message);
    void onSocketError(QAbstractSocket::SocketError error);
    void onSendTimer();

private:
    QUrl buildRequestUrl() const;
    QByteArray hmacSha1(const QByteArray& key, const QByteArray& data) const;
    static QString expandEnv(const QString& value);

    QString m_secretId;
    QString m_secretKey;
    QString m_appId;
    int m_vadSilenceTimeMs;
    bool m_initialized;
    bool m_wantStreaming;
    bool m_handshook;
    QWebSocket* m_socket;
    QTimer* m_sendTimer;
    QByteArray m_sendBuffer;
};

#endif // TENCENTSPEECHRECOGNIZER_H
