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

#include "TencentSpeechRecognizer.h"

#include <algorithm>
#include <QCryptographicHash>
#include <QMessageAuthenticationCode>
#include <QDateTime>
#include <QRandomGenerator>
#include <QUuid>
#include <QUrl>
#include <QPair>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QProcessEnvironment>

namespace {
const QString kHost = QStringLiteral("asr.cloud.tencent.com");
const int kPacketBytes = 6400; // 200ms of 16kHz mono int16
const int kDefaultVadSilenceTimeMs = 1200;
const int kMinVadSilenceTimeMs = 240;
const int kMaxVadSilenceTimeMs = 2000;
}

TencentSpeechRecognizer::TencentSpeechRecognizer(QObject* parent)
    : QObject(parent)
    , m_vadSilenceTimeMs(kDefaultVadSilenceTimeMs)
    , m_initialized(false)
    , m_wantStreaming(false)
    , m_handshook(false)
    , m_socket(new QWebSocket(QString(), QWebSocketProtocol::VersionLatest, this))
    , m_sendTimer(new QTimer(this))
{
    connect(m_socket, &QWebSocket::connected, this, &TencentSpeechRecognizer::onConnected);
    connect(m_socket, &QWebSocket::disconnected, this, &TencentSpeechRecognizer::onDisconnected);
    connect(m_socket, &QWebSocket::textMessageReceived, this, &TencentSpeechRecognizer::onTextMessage);
#if QT_VERSION >= QT_VERSION_CHECK(6, 5, 0)
    connect(m_socket, &QWebSocket::errorOccurred, this, &TencentSpeechRecognizer::onSocketError);
#else
    connect(m_socket, QOverload<QAbstractSocket::SocketError>::of(&QWebSocket::error),
        this, &TencentSpeechRecognizer::onSocketError);
#endif
    m_sendTimer->setInterval(200);
    connect(m_sendTimer, &QTimer::timeout, this, &TencentSpeechRecognizer::onSendTimer);
}

TencentSpeechRecognizer::~TencentSpeechRecognizer()
{
    stopRealtime();
}

QString TencentSpeechRecognizer::expandEnv(const QString& value)
{
    const QString trimmed = value.trimmed();
    if (trimmed.size() >= 4 && trimmed.startsWith(QLatin1String("${")) && trimmed.endsWith(QLatin1Char('}'))) {
        const QString name = trimmed.mid(2, trimmed.size() - 3);
        return QProcessEnvironment::systemEnvironment().value(name);
    }
    return trimmed;
}

void TencentSpeechRecognizer::setCredentials(const QString& secretId, const QString& secretKey, const QString& appId)
{
    m_secretId = expandEnv(secretId);
    m_secretKey = expandEnv(secretKey);
    m_appId = expandEnv(appId);
    if (m_appId.isEmpty()) {
        m_appId = expandEnv(QStringLiteral("${TENCENT_APP_ID}"));
    }
    m_initialized = !m_secretId.isEmpty() && !m_secretKey.isEmpty() && !m_appId.isEmpty();
    if (!m_initialized) {
        ERROR_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime ASR needs secret_id, secret_key, and app_id");
    }
}

void TencentSpeechRecognizer::setVadSilenceTime(int ms)
{
    if (ms <= 0) {
        m_vadSilenceTimeMs = kDefaultVadSilenceTimeMs;
    }
    else {
        m_vadSilenceTimeMs = qBound(kMinVadSilenceTimeMs, ms, kMaxVadSilenceTimeMs);
    }
    FINE_DEBUG_OUTPUT(QString("[Tencent Speech Recognizer]vad_silence_time=%1ms")
        .arg(m_vadSilenceTimeMs));
}

bool TencentSpeechRecognizer::isInitialized() const
{
    return m_initialized;
}

bool TencentSpeechRecognizer::isStreaming() const
{
    return m_wantStreaming;
}

QByteArray TencentSpeechRecognizer::hmacSha1(const QByteArray& key, const QByteArray& data) const
{
    return QMessageAuthenticationCode::hash(data, key, QCryptographicHash::Sha1);
}

QUrl TencentSpeechRecognizer::buildRequestUrl() const
{
    const qint64 timestamp = QDateTime::currentSecsSinceEpoch();
    const qint64 expired = timestamp + 24 * 3600;
    const quint32 nonce = QRandomGenerator::global()->bounded(1, 1000000000);
    const QString voiceId = QUuid::createUuid().toString(QUuid::WithoutBraces);

    QList<QPair<QString, QString>> params;
    params.append({QStringLiteral("engine_model_type"), QStringLiteral("16k_zh")});
    params.append({QStringLiteral("expired"), QString::number(expired)});
    params.append({QStringLiteral("needvad"), QStringLiteral("1")});
    params.append({QStringLiteral("nonce"), QString::number(nonce)});
    params.append({QStringLiteral("secretid"), m_secretId});
    params.append({QStringLiteral("timestamp"), QString::number(timestamp)});
    params.append({QStringLiteral("vad_silence_time"), QString::number(m_vadSilenceTimeMs)});
    params.append({QStringLiteral("voice_format"), QStringLiteral("1")});
    params.append({QStringLiteral("voice_id"), voiceId});
    std::sort(params.begin(), params.end(), [](const auto& a, const auto& b) {
        return a.first < b.first;
    });

    QString query;
    for (int i = 0; i < params.size(); ++i) {
        if (i > 0) {
            query += QLatin1Char('&');
        }
        query += params[i].first;
        query += QLatin1Char('=');
        query += params[i].second;
    }

    const QString origin = kHost + QStringLiteral("/asr/v2/") + m_appId + QLatin1Char('?') + query;
    const QByteArray digest = hmacSha1(m_secretKey.toUtf8(), origin.toUtf8());
    const QByteArray signature = QUrl::toPercentEncoding(QString::fromLatin1(digest.toBase64()));
    const QUrl url(QStringLiteral("wss://") + origin + QStringLiteral("&signature=") + QString::fromLatin1(signature));
    return url;
}

bool TencentSpeechRecognizer::startRealtime()
{
    if (!m_initialized) {
        emit errorOccurred("[Tencent Speech Recognizer]TencentCloud authentication information havent beem set!");
        return false;
    }
    if (m_wantStreaming) {
        return true;
    }

    m_wantStreaming = true;
    m_handshook = false;
    m_sendBuffer.clear();
    const QUrl url = buildRequestUrl();
    FINE_DEBUG_OUTPUT("[Tencent Speech Recognizer]Opening realtime ASR websocket");
    m_socket->open(url);
    return true;
}

void TencentSpeechRecognizer::stopRealtime()
{
    m_wantStreaming = false;
    m_sendTimer->stop();
    if (m_socket->state() == QAbstractSocket::ConnectedState) {
        if (!m_sendBuffer.isEmpty()) {
            m_socket->sendBinaryMessage(m_sendBuffer);
            m_sendBuffer.clear();
        }
        m_socket->sendTextMessage(QStringLiteral("{\"type\":\"end\"}"));
        m_socket->close();
    }
    else if (m_socket->state() != QAbstractSocket::UnconnectedState) {
        m_socket->abort();
    }
    m_handshook = false;
    FINE_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime ASR stopped");
}

void TencentSpeechRecognizer::sendAudio(const QByteArray& pcm)
{
    if (!m_wantStreaming || pcm.isEmpty()) {
        return;
    }
    m_sendBuffer.append(pcm);
}

void TencentSpeechRecognizer::onConnected()
{
    FINE_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime socket connected, waiting handshake");
}

void TencentSpeechRecognizer::onDisconnected()
{
    m_sendTimer->stop();
    m_handshook = false;
    FINE_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime socket disconnected");
    if (m_wantStreaming) {
        ERROR_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime socket dropped while listening, reconnecting");
        QTimer::singleShot(500, this, [this]() {
            if (!m_wantStreaming) {
                return;
            }
            m_socket->open(buildRequestUrl());
        });
    }
}

void TencentSpeechRecognizer::onSocketError(QAbstractSocket::SocketError error)
{
    Q_UNUSED(error);
    ERROR_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime socket error: " + m_socket->errorString());
    emit errorOccurred("[Tencent Speech Recognizer]Request failed: " + m_socket->errorString());
}

void TencentSpeechRecognizer::onTextMessage(const QString& message)
{
    QJsonParseError parseError;
    const QJsonDocument doc = QJsonDocument::fromJson(message.toUtf8(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !doc.isObject()) {
        ERROR_DEBUG_OUTPUT("[Tencent Speech Recognizer]JSON analysis error: " + parseError.errorString());
        return;
    }

    const QJsonObject obj = doc.object();
    const int code = obj.value(QStringLiteral("code")).toInt(-1);
    if (code != 0) {
        const QString err = obj.value(QStringLiteral("message")).toString();
        ERROR_DEBUG_OUTPUT("[Tencent Speech Recognizer]TencentClout API error: " + err);
        emit errorOccurred("[Tencent Speech Recognizer]TencentClout API error: " + err);
        if (code == 4002 || code == 4003 || code == 4001) {
            m_wantStreaming = false;
        }
        return;
    }

    if (!m_handshook) {
        m_handshook = true;
        m_sendTimer->start();
        FINE_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime handshake ok");
    }

    const bool streamEnded = obj.value(QStringLiteral("final")).toInt() == 1;
    if (streamEnded) {
        FINE_DEBUG_OUTPUT("[Tencent Speech Recognizer]Realtime stream final=1");
    }

    if (!obj.contains(QStringLiteral("result"))) {
        return;
    }
    const QJsonObject result = obj.value(QStringLiteral("result")).toObject();
    const QString text = result.value(QStringLiteral("voice_text_str")).toString().trimmed();
    const int sliceType = result.value(QStringLiteral("slice_type")).toInt(-1);
    const bool isFinal = streamEnded || (sliceType == 2);
    FINE_DEBUG_OUTPUT(QString("[Tencent Speech Recognizer]transcript final=%1 slice=%2 text=%3")
        .arg(isFinal ? "true" : "false")
        .arg(sliceType)
        .arg(text));
    if (!text.isEmpty()) {
        emit transcriptReceived(text, isFinal, sliceType);
    }
}

void TencentSpeechRecognizer::onSendTimer()
{
    if (!m_wantStreaming || m_socket->state() != QAbstractSocket::ConnectedState || !m_handshook) {
        return;
    }
    QByteArray packet;
    if (m_sendBuffer.size() >= kPacketBytes) {
        packet = m_sendBuffer.left(kPacketBytes);
        m_sendBuffer.remove(0, kPacketBytes);
    }
    else if (!m_sendBuffer.isEmpty()) {
        packet = m_sendBuffer;
        m_sendBuffer.clear();
    }
    else {
        packet = QByteArray(kPacketBytes, '\0');
    }
    m_socket->sendBinaryMessage(packet);
}
