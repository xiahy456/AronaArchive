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

#include "WebSocketController.h"
#include <QDebug>
#include <QJsonArray>
#include <QDateTime>
#include <QAbstractSocket>

WebSocketController::WebSocketController(QObject* parent)
    : QObject(parent)
    , m_webSocket(new QWebSocket(QString(), QWebSocketProtocol::VersionLatest, this))
    , m_heartbeatTimer(new QTimer(this))
    , m_heartbeatCheckTimer(new QTimer(this))
    , m_reconnectTimer(new QTimer(this))
    , m_connectTimeoutTimer(new QTimer(this))
    , m_currentState(ConnectionState::Disconnected)
    , m_serverUrl(GET_STRING_FROM_JSON(_global_config, "aronalm", "websocket_url")) // websocket地址
    , m_heartbeatInterval(GET_INT_FROM_JSON(_global_config, "aronalm", "heartbeat_interval"))   // 心跳间隔
    , m_heartbeatTimeout(GET_INT_FROM_JSON(_global_config, "aronalm", "heartbeat_timeout")) // 心跳超时
    , m_reconnectInterval(GET_INT_FROM_JSON(_global_config, "aronalm", "reconnect_interval"))   // 重连间隔
    , m_maxReconnectAttempts(GET_INT_FROM_JSON(_global_config, "aronalm", "max_reconnect_attempts"))    // 最多重连
    , m_currentReconnectCount(0)
    , m_autoReconnect(true)
    , m_pongReceived(false)
    , m_cacheMessages(true)
{
    // 连接WebSocket信号
    connect(m_webSocket, &QWebSocket::connected, this, [this]() {
        onConnected();
        });
    connect(m_webSocket, &QWebSocket::disconnected,
        this, &WebSocketController::onDisconnected);
    connect(m_webSocket, &QWebSocket::textMessageReceived,
        this, &WebSocketController::onTextMessageReceived);

    // Qt 6.5+ 使用 errorOccurred，之前版本使用 error
#if QT_VERSION >= QT_VERSION_CHECK(6, 5, 0)
    connect(m_webSocket, &QWebSocket::errorOccurred, this,
        [this](QAbstractSocket::SocketError error) {
            onError(error);
        });
#else
    connect(m_webSocket, QOverload<QAbstractSocket::SocketError>::of(&QWebSocket::error),
        this, &WebSocketController::onError);
#endif

    // 心跳计时器
    connect(m_heartbeatTimer, &QTimer::timeout,
        this, &WebSocketController::onHeartbeatTimer);

    // 心跳检查计时器（单次触发）
    m_heartbeatCheckTimer->setSingleShot(true);
    connect(m_heartbeatCheckTimer, &QTimer::timeout,
        this, &WebSocketController::onHeartbeatCheckTimer);

    // 重连计时器
    connect(m_reconnectTimer, &QTimer::timeout,
        this, &WebSocketController::onReconnectTimer);

    m_connectTimeoutTimer->setSingleShot(true);
    connect(m_connectTimeoutTimer, &QTimer::timeout,
        this, &WebSocketController::onConnectTimeout);
}

WebSocketController::~WebSocketController()
{
    stopHeartbeat();
    stopReconnect();
    stopConnectTimeout();

    if (m_webSocket->state() == QAbstractSocket::ConnectedState) {
        m_webSocket->close();
    }
}

// ========== 连接管理实现 ==========

void WebSocketController::connectToServer()
{
    if (m_serverUrl.isEmpty()) {
        emit errorOccurred(ErrorCode::ConnectionRefused, "服务器URL未设置");
        if (m_onErrorOccurredCallback) {
            m_onErrorOccurredCallback(ErrorCode::ConnectionRefused, "服务器URL未设置");
        }
        return;
    }

    if (m_currentState == ConnectionState::Connected ||
        m_currentState == ConnectionState::Connecting) {
        FINE_DEBUG_OUTPUT("[WebSocketController]Already connected or connecting...");
        return;
    }

    setState(ConnectionState::Connecting);

    FINE_DEBUG_OUTPUT("[WebSocketController]Connecting to: " + m_serverUrl);
    startConnectTimeout();
    m_webSocket->open(QUrl(m_serverUrl));
}

void WebSocketController::disconnectFromServer()
{
    m_autoReconnect = false;  // 手动断开时不自动重连
    stopHeartbeat();
    stopReconnect();
    stopConnectTimeout();

    if (m_webSocket->state() == QAbstractSocket::ConnectedState) {
        m_webSocket->close();
    }

    setState(ConnectionState::Disconnected);
    m_currentReconnectCount = 0;
}

WebSocketController::ConnectionState WebSocketController::state() const
{
    return m_currentState;
}

bool WebSocketController::isConnected() const
{
    return m_currentState == ConnectionState::Connected;
}

// ========== 配置实现 ==========

void WebSocketController::setServerUrl(const QString& url)
{
    m_serverUrl = url;
}

void WebSocketController::setHeartbeatInterval(int intervalMs)
{
    m_heartbeatInterval = intervalMs;
}

void WebSocketController::setHeartbeatTimeout(int timeoutMs)
{
    m_heartbeatTimeout = timeoutMs;
}

void WebSocketController::setReconnectInterval(int intervalMs)
{
    m_reconnectInterval = intervalMs;
}

void WebSocketController::setMaxReconnectAttempts(int attempts)
{
    m_maxReconnectAttempts = attempts;
}

void WebSocketController::setAutoReconnect(bool enabled)
{
    m_autoReconnect = enabled;
}

// ========== 消息发送实现 ==========

void WebSocketController::sendChatMessage(const QString& content,
    bool useRag, bool useMemory, const QString& imageBase64)
{
    QJsonObject message;
    message["type"] = "chat";
    message["content"] = content;

    QJsonObject options;
    options["use_rag"] = useRag;
    options["use_memory"] = useMemory;
    message["options"] = options;
    if (!imageBase64.isEmpty()) {
        QJsonObject image;
        image["mime"] = QStringLiteral("image/jpeg");
        image["data"] = imageBase64;
        message["image"] = image;
    }

    sendMessage(message);
}

void WebSocketController::sendInteract(const QString& action, int durationMs)
{
    QJsonObject message;
    message["type"] = QStringLiteral("interact");
    message["action"] = action;
    message["duration_ms"] = durationMs;
    sendMessage(message);
}

void WebSocketController::sendListenState(bool listening)
{
    QJsonObject message;
    message["type"] = "listen_state";
    message["state"] = listening ? QStringLiteral("on") : QStringLiteral("off");
    sendMessage(message);
}

void WebSocketController::sendTranscript(const QString& text, const QString& segmentId, int silenceMs,
    const QString& imageBase64)
{
    QJsonObject message;
    message["type"] = "transcript";
    message["content"] = text;
    message["speaker"] = QStringLiteral("teacher");
    message["is_final"] = true;
    message["segment_id"] = segmentId;
    message["silence_ms"] = silenceMs;
    if (!imageBase64.isEmpty()) {
        QJsonObject image;
        image["mime"] = QStringLiteral("image/jpeg");
        image["data"] = imageBase64;
        message["image"] = image;
    }
    sendMessage(message);
}

void WebSocketController::sendInterrupt()
{
    QJsonObject message;
    message["type"] = "interrupt";
    sendMessage(message);
}

void WebSocketController::sendComputerUseObservation(const QJsonObject& observation)
{
    QJsonObject message = observation;
    message["type"] = QStringLiteral("computer_use_observation");
    sendMessage(message);
}

void WebSocketController::sendGlanceFrame(const QString& requestId, const QString& imageBase64)
{
    QJsonObject message;
    message["type"] = QStringLiteral("glance_frame");
    message["request_id"] = requestId;
    if (!imageBase64.isEmpty()) {
        QJsonObject image;
        image["mime"] = QStringLiteral("image/jpeg");
        image["data"] = imageBase64;
        message["image"] = image;
    }
    sendMessage(message);
}

void WebSocketController::sendGlanceRefused(const QString& requestId)
{
    QJsonObject message;
    message["type"] = QStringLiteral("glance_refused");
    message["request_id"] = requestId;
    sendMessage(message);
}

void WebSocketController::clearSession()
{
    QJsonObject message;
    message["type"] = "clear_session";
    sendMessage(message);
}

void WebSocketController::getStats()
{
    QJsonObject message;
    message["type"] = "get_stats";
    sendMessage(message);
}

void WebSocketController::sendPing()
{
    QJsonObject message;
    message["type"] = "ping";
    sendMessage(message);
}

void WebSocketController::sendMessage(const QJsonObject& message)
{
    if (m_currentState == ConnectionState::Connected) {
        sendJsonMessage(message);
    }
    else if (m_cacheMessages) {
        // 未连接时缓存消息（队列最多缓存100条）
        if (m_messageQueue.size() < 100) {
            m_messageQueue.enqueue(message);
            FINE_DEBUG_OUTPUT("[WebSocketController]Messaged cached, queue's size:" + QString::number(m_messageQueue.size()));
        }
        else {
            ERROR_DEBUG_OUTPUT("[WebSocketController]Message queue is full, discard message");
        }
    }
    else {
        ERROR_DEBUG_OUTPUT("[WebSocketController]Not connected, cannot send message");
    }
}

void WebSocketController::sendJsonMessage(const QJsonObject& message)
{
    QJsonDocument doc(message);
    QString jsonString = doc.toJson(QJsonDocument::Compact);
    m_webSocket->sendTextMessage(jsonString);
}

// ========== 回调注册实现 ==========

void WebSocketController::onMessageReceived(MessageCallback callback)
{
    m_onMessageCallback = callback;
}

void WebSocketController::onChatResponse(MessageCallback callback)
{
    m_onChatResponseCallback = callback;
}

void WebSocketController::onError(ErrorCallback callback)
{
    m_onErrorCallback = callback;
}

void WebSocketController::onConnectionStateChanged(StateCallback callback)
{
    m_onStateChangedCallback = callback;
}

void WebSocketController::onConnected(MessageCallback callback)
{
    m_onConnectedCallback = callback;
}

void WebSocketController::onStatsReceived(MessageCallback callback)
{
    m_onStatsCallback = callback;
}

void WebSocketController::onResult(MessageCallback callback)
{
    m_onResultCallback = callback;
}

void WebSocketController::onPong(MessageCallback callback)
{
    m_onPongCallback = callback;
}

void WebSocketController::onErrorOccurred(ErrorCallback callback)
{
    m_onErrorOccurredCallback = callback;
}

// ========== 内部槽函数实现 ==========

void WebSocketController::onConnected()
{
    FINE_DEBUG_OUTPUT("[WebSocketController]Connected to server");
    stopConnectTimeout();
    setState(ConnectionState::Connected);
    m_currentReconnectCount = 0;
    m_pongReceived = true;

    // 启动心跳
    startHeartbeat();

    // 发送缓存的消息
    while (!m_messageQueue.isEmpty() && m_currentState == ConnectionState::Connected) {
        QJsonObject message = m_messageQueue.dequeue();
        sendJsonMessage(message);
    }
}

void WebSocketController::onDisconnected()
{
    FINE_DEBUG_OUTPUT("[WebSocketController]Disconnected from server");
    stopHeartbeat();
    stopConnectTimeout();

    if (m_currentState == ConnectionState::Connected) {
        setState(ConnectionState::Disconnected);
        emit disconnected();

        if (m_autoReconnect) {
            startReconnect();
        }
        return;
    }

    if (m_currentState == ConnectionState::Connecting
        || m_currentState == ConnectionState::Reconnecting) {
        emit errorOccurred(ErrorCode::ConnectionRefused, QStringLiteral("无法连接到AI服务"));
        if (m_onErrorOccurredCallback) {
            m_onErrorOccurredCallback(ErrorCode::ConnectionRefused, QStringLiteral("无法连接到AI服务"));
        }
        handleConnectAttemptFailed();
    }
}

void WebSocketController::onTextMessageReceived(const QString& message)
{
    QJsonParseError error;
    QJsonDocument doc = QJsonDocument::fromJson(message.toUtf8(), &error);

    if (error.error != QJsonParseError::NoError) {
        ERROR_DEBUG_OUTPUT("[WebSocketController]JSON parse error: " + error.errorString());
        emit errorOccurred(ErrorCode::InvalidMessage, "无效的JSON格式: " + error.errorString());
        return;
    }

    if (!doc.isObject()) {
        ERROR_DEBUG_OUTPUT("[WebSocketController]Message is not a JSON object");
        return;
    }

    QJsonObject jsonObj = doc.object();

    // 重置心跳超时计时器（收到任何消息都视为连接活跃）
    resetHeartbeatTimer();

    // 处理消息
    handleMessage(jsonObj);

    // 触发通用消息回调
    if (m_onMessageCallback) {
        m_onMessageCallback(jsonObj);
    }

    emit messageReceived(jsonObj);
}

void WebSocketController::onError(QAbstractSocket::SocketError error)
{
    QString errorMsg = m_webSocket->errorString();
    ErrorCode code = mapSocketError(error);
    ERROR_DEBUG_OUTPUT(QString("[WebSocketController]WebSocket error: %1 (socket=%2 code=%3)")
        .arg(errorMsg)
        .arg(static_cast<int>(error))
        .arg(static_cast<int>(code)));

    emit errorOccurred(code, errorMsg);

    if (m_onErrorOccurredCallback) {
        m_onErrorOccurredCallback(code, errorMsg);
    }

    stopConnectTimeout();
    if (m_currentState == ConnectionState::Connecting
        || m_currentState == ConnectionState::Reconnecting) {
        handleConnectAttemptFailed();
    }
}

WebSocketController::ErrorCode WebSocketController::mapSocketError(QAbstractSocket::SocketError error)
{
    switch (error) {
    case QAbstractSocket::ConnectionRefusedError:
    case QAbstractSocket::HostNotFoundError:
    case QAbstractSocket::ProxyConnectionRefusedError:
        return ErrorCode::ConnectionRefused;
    case QAbstractSocket::SocketTimeoutError:
    case QAbstractSocket::ProxyConnectionTimeoutError:
        return ErrorCode::ConnectionTimeout;
    default:
        return ErrorCode::NetworkError;
    }
}

void WebSocketController::onHeartbeatTimer()
{
    if (m_currentState == ConnectionState::Connected) {
        // 检查上一次心跳是否收到响应
        if (!m_pongReceived) {
            ERROR_DEBUG_OUTPUT("[WebSocketController]Heartbeat timeout, no pong response received");
            emit heartbeatTimeout();

            // 断开连接并重连
            m_webSocket->close();
            return;
        }

        // 发送心跳
        m_pongReceived = false;
        sendPing();

        // 启动心跳超时检查
        m_heartbeatCheckTimer->start(m_heartbeatTimeout);
    }
}

void WebSocketController::onHeartbeatCheckTimer()
{
    if (!m_pongReceived) {
        ERROR_DEBUG_OUTPUT("[WebSocketController]Heartbeat check timeout");
        emit heartbeatTimeout();

        // 断开连接并重连
        m_webSocket->close();
    }
}

void WebSocketController::onReconnectTimer()
{
    if (m_currentState == ConnectionState::Connected ||
        m_currentState == ConnectionState::Connecting) {
        return;
    }

    if (m_maxReconnectAttempts != -1 &&
        m_currentReconnectCount >= m_maxReconnectAttempts) {
        ERROR_DEBUG_OUTPUT("[WebSocketController]Maximum reconnect attempts reached, stopping reconnect");
        stopReconnect();

        emit errorOccurred(ErrorCode::ReconnectFailed,
            QString("重连失败，已尝试%1次").arg(m_currentReconnectCount));
        if (m_onErrorOccurredCallback) {
            m_onErrorOccurredCallback(ErrorCode::ReconnectFailed,
                QString("重连失败，已尝试%1次").arg(m_currentReconnectCount));
        }
        return;
    }

    m_currentReconnectCount++;
    FINE_DEBUG_OUTPUT("[WebSocketController]Attempting to reconnect (" + QString::number(m_currentReconnectCount) + "/"
        + (m_maxReconnectAttempts == -1 ? "∞" : QString::number(m_maxReconnectAttempts)) + ")");

    setState(ConnectionState::Reconnecting);
    startConnectTimeout();
    m_webSocket->open(QUrl(m_serverUrl));
}

void WebSocketController::onPongReceived()
{
    m_pongReceived = true;
    m_heartbeatCheckTimer->stop();
}

void WebSocketController::onConnectTimeout()
{
    if (m_currentState != ConnectionState::Connecting
        && m_currentState != ConnectionState::Reconnecting) {
        return;
    }

    ERROR_DEBUG_OUTPUT("[WebSocketController]Connect timeout");
    emit errorOccurred(ErrorCode::ConnectionTimeout, QStringLiteral("连接AI服务超时"));
    if (m_onErrorOccurredCallback) {
        m_onErrorOccurredCallback(ErrorCode::ConnectionTimeout, QStringLiteral("连接AI服务超时"));
    }

    m_webSocket->abort();
    handleConnectAttemptFailed();
}

void WebSocketController::startConnectTimeout()
{
    const int timeoutMs = m_heartbeatTimeout > 0 ? m_heartbeatTimeout : 10000;
    m_connectTimeoutTimer->start(timeoutMs);
}

void WebSocketController::stopConnectTimeout()
{
    m_connectTimeoutTimer->stop();
}

void WebSocketController::handleConnectAttemptFailed()
{
    if (m_currentState != ConnectionState::Connecting
        && m_currentState != ConnectionState::Reconnecting) {
        return;
    }

    stopConnectTimeout();
    setState(ConnectionState::Disconnected);
    if (m_autoReconnect) {
        startReconnect();
    }
}

// ========== 消息处理实现 ==========

void WebSocketController::handleMessage(const QJsonObject& message)
{
    QString type = message["type"].toString();

    if (type == "chat_response") {
        handleChatResponse(message);
    }
    else if (type == "presence") {
        handlePresence(message);
    }
    else if (type == "computer_use_action") {
        handleComputerUseAction(message);
    }
    else if (type == "computer_use_done") {
        handleComputerUseDone(message);
    }
    else if (type == "glance_request") {
        emit glanceRequested(message["request_id"].toString());
    }
    else if (type == "error") {
        handleError(message);
    }
    else if (type == "connected") {
        handleConnected(message);
    }
    else if (type == "stats") {
        handleStats(message);
    }
    else if (type == "result") {
        handleResult(message);
    }
    else if (type == "pong") {
        handlePong(message);
    }
    else {
        FINE_DEBUG_OUTPUT("[WebSocketController]Unknown message type: " + type);
    }
}

void WebSocketController::handleChatResponse(const QJsonObject& message)
{
    QString content = message["content"].toString();
    QString contextUsed = message["context_used"].toString("none");
    double latency = message["latency"].toDouble(0.0);
    QString emotion = message["emotion"].toString("normal");
    if (emotion.trimmed().isEmpty()) {
        emotion = QStringLiteral("normal");
    }

    FINE_DEBUG_OUTPUT("[WebSocketController]Received chat response: " + content.left(50)
        + "... emotion=" + emotion);

    emit chatResponseReceived(content, contextUsed, latency, emotion);

    if (m_onChatResponseCallback) {
        m_onChatResponseCallback(message);
    }
}

void WebSocketController::handlePresence(const QJsonObject& message)
{
    QString emotion = message["emotion"].toString("normal");
    if (emotion.trimmed().isEmpty()) {
        emotion = QStringLiteral("normal");
    }
    FINE_DEBUG_OUTPUT(QString("[WebSocketController] Received presence emotion=%1 activity=%2")
        .arg(emotion)
        .arg(message["activity"].toString()));
    emit presenceReceived(emotion);
}

void WebSocketController::handleComputerUseAction(const QJsonObject& message)
{
    QString extra;
    if (message.contains(QStringLiteral("x")) && !message.value(QStringLiteral("x")).isNull()
        && message.contains(QStringLiteral("y")) && !message.value(QStringLiteral("y")).isNull()) {
        extra = QString(" x=%1 y=%2 coord_space=%3")
            .arg(message.value(QStringLiteral("x")).toDouble())
            .arg(message.value(QStringLiteral("y")).toDouble())
            .arg(message.value(QStringLiteral("coord_space")).toString());
    }
    FINE_DEBUG_OUTPUT(QString("[WebSocketController] computer_use_action run=%1 step=%2 action=%3%4")
        .arg(message.value(QStringLiteral("run_id")).toString())
        .arg(message.value(QStringLiteral("step")).toInt())
        .arg(message.value(QStringLiteral("action")).toString())
        .arg(extra));
    emit computerUseActionReceived(message);
}

void WebSocketController::handleComputerUseDone(const QJsonObject& message)
{
    FINE_DEBUG_OUTPUT(QString("[WebSocketController] computer_use_done run=%1 ok=%2 summary=%3")
        .arg(message.value(QStringLiteral("run_id")).toString())
        .arg(message.value(QStringLiteral("ok")).toBool() ? "true" : "false")
        .arg(message.value(QStringLiteral("summary")).toString()));
    emit computerUseDoneReceived(message);
}

void WebSocketController::handleError(const QJsonObject& message)
{
    QString code = message["code"].toString();
    QString errorMsg = message["message"].toString();

    ERROR_DEBUG_OUTPUT("[WebSocketController]Server error: " + code + "-" + errorMsg);

    ErrorCode errorCode = ErrorCode::ProtocolError;
    if (code == "INVALID_JSON") errorCode = ErrorCode::InvalidMessage;

    emit errorOccurred(errorCode, errorMsg);

    if (m_onErrorCallback) {
        m_onErrorCallback(errorCode, errorMsg);
    }
}

void WebSocketController::handleConnected(const QJsonObject& message)
{
    QString sessionId = message["session_id"].toString();
    FINE_DEBUG_OUTPUT("[WebSocketController]Session established, session_id: " + sessionId);

    emit connected(sessionId);

    if (m_onConnectedCallback) {
        m_onConnectedCallback(message);
    }
}

void WebSocketController::handleStats(const QJsonObject& message)
{
    FINE_DEBUG_OUTPUT("[WebSocketController]Received statistics");

    if (m_onStatsCallback) {
        m_onStatsCallback(message);
    }
}

void WebSocketController::handleResult(const QJsonObject& message)
{
    bool success = message["success"].toBool();
    QString resultMsg = message["message"].toString();
    FINE_DEBUG_OUTPUT("WebSocketController: 操作结果 - 成功:" + (QString)(success ? "true" : "false") + " 消息:" + resultMsg);

    if (m_onResultCallback) {
        m_onResultCallback(message);
    }
}

void WebSocketController::handlePong(const QJsonObject& message)
{
    FINE_DEBUG_OUTPUT("[WebSocketController]Received pong response");
    onPongReceived();

    if (m_onPongCallback) {
        m_onPongCallback(message);
    }
}

// ========== 心跳管理实现 ==========

void WebSocketController::startHeartbeat()
{
    stopHeartbeat();
    m_pongReceived = true;
    m_heartbeatTimer->start(m_heartbeatInterval);
    FINE_DEBUG_OUTPUT("[WebSocketController]Heartbeat started, interval: " + QString::number(m_heartbeatInterval) + "ms");
}

void WebSocketController::stopHeartbeat()
{
    m_heartbeatTimer->stop();
    m_heartbeatCheckTimer->stop();
    FINE_DEBUG_OUTPUT("[WebSocketController]Heartbeat stopped");
}

void WebSocketController::resetHeartbeatTimer()
{
    if (m_currentState == ConnectionState::Connected) {
        m_pongReceived = true;
        m_heartbeatCheckTimer->stop();
        // 重置心跳发送计时器
        m_heartbeatTimer->start(m_heartbeatInterval);
    }
}

// ========== 重连管理实现 ==========

void WebSocketController::startReconnect()
{
    if (!m_reconnectTimer->isActive()) {
        m_reconnectTimer->start(m_reconnectInterval);
        FINE_DEBUG_OUTPUT("[WebSocketController]Reconnect started, interval: " + QString::number(m_reconnectInterval) + "ms");
    }
}

void WebSocketController::stopReconnect()
{
    m_reconnectTimer->stop();
    m_currentReconnectCount = 0;
    FINE_DEBUG_OUTPUT("[WebSocketController]Reconnect stopped");
}

void WebSocketController::setState(ConnectionState newState)
{
    if (m_currentState != newState) {
        m_currentState = newState;

        QString stateStr;
        switch (newState) {
        case ConnectionState::Disconnected: stateStr = "Disconnected"; break;
        case ConnectionState::Connecting: stateStr = "Connecting"; break;
        case ConnectionState::Connected: stateStr = "Connected"; break;
        case ConnectionState::Reconnecting: stateStr = "Reconnecting"; break;
        }
        FINE_DEBUG_OUTPUT("[WebSocketController]State changed to: " + stateStr);

        emit connectionStateChanged(newState);

        if (m_onStateChangedCallback) {
            m_onStateChangedCallback(newState);
        }
    }
}