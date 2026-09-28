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
