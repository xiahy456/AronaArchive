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

#include "TTSManager.h"
#include <QDebug>
#include <QHttpMultiPart>
#include <QAudio>
#include <QAudioFormat>
#include <QAudioSink>
#include <QTimer>
#include <QFileInfo>
#include <QIODevice>
#include <cstring>

TTSManager::TTSManager(QObject* parent)
    : QObject(parent)
    , networkManager(new QNetworkAccessManager(this))
    , serverHost()
    , serverPort(0)
    , m_minimalBackend(false)
    , m_streaming(false)
    , m_voice()
    , currentReply(nullptr)
    , currentMediaType()
    , audioSink(nullptr)
    , audioBuffer(nullptr)
    , m_streamPush(nullptr)
    , m_streamWritten(0)
    , isProcessingRequest(false)
    , m_awaitingPlayback(false)
    , m_playingAudio(false)
    , m_ignoreAudioIdle(false)
    , m_currentIsWarmup(false)
    , m_restartingStream(false)
    , m_streamFeedScheduled(false)
    , m_streamEndScheduled(false)
    , m_inStreamFeed(false)
    , m_playbackGeneration(0)
    , requestTimeoutMs(45000)
{
    const QString backend = GET_STRING_FROM_JSON(_global_config, "tts", "backend").trimmed().toLower();
    m_minimalBackend = (backend == QLatin1String("minimal"));
    m_streaming = GET_BOOL_FROM_JSON(_global_config, "tts", "streaming");
    m_voice = GET_STRING_FROM_JSON(_global_config, "tts", "voice").trimmed();
    if (m_voice.isEmpty()) {
        m_voice = QStringLiteral("arona");
    }

    QString host = GET_STRING_FROM_JSON(_global_config, "tts", "host");
    int port = GET_INT_FROM_JSON(_global_config, "tts", "port");
    if (m_minimalBackend) {
        const QString minimalHost = GET_STRING_FROM_JSON(_global_config, "tts", "minimal_host").trimmed();
        if (!minimalHost.isEmpty()) {
            host = minimalHost;
        }
        const int minimalPort = GET_INT_FROM_JSON(_global_config, "tts", "minimal_port");
        port = (minimalPort > 0) ? minimalPort : 8000;
        if (host.isEmpty()) {
            host = QStringLiteral("127.0.0.1");
        }
    }

    setServerAddress(host, port);
    FINE_DEBUG_OUTPUT(QString("[TTS Operation]Set server : backend=%1 Host: %2 | Port: %3 | streaming=%4")
        .arg(m_minimalBackend ? QStringLiteral("minimal") : QStringLiteral("official"),
            serverHost, QString::number(serverPort),
            m_streaming ? QStringLiteral("true") : QStringLiteral("false")));

    int configuredTimeout = GET_INT_FROM_JSON(_global_config, "tts", "request_timeout_ms");
    if (configuredTimeout > 0) {
        requestTimeoutMs = configuredTimeout;
    }
    FINE_DEBUG_OUTPUT("[TTS Operation]Request timeout: " + QString::number(requestTimeoutMs) + " ms");

	// 连接网络请求完成的信号到槽函数
    connect(networkManager, &QNetworkAccessManager::finished,
        this, &TTSManager::onNetworkReplyFinished);

}

TTSManager::~TTSManager()
{
    cleanupCurrentReply();
    requestQueue.clear();
    m_readyPlayback.clear();
    m_currentReceive.clear();
    m_deliveredStream.clear();
    stopAudioSink();
}

void TTSManager::setServerAddress(const QString& host, int port)
{
    serverHost = host;
    serverPort = port;
}

bool TTSManager::isMinimalBackend() const
{
    return m_minimalBackend;
}

bool TTSManager::isStreaming() const
{
    return m_streaming;
}

void TTSManager::cleanupCurrentReply()
{
    if (currentReply) {
        // 断开所有连接
        currentReply->disconnect();
        currentReply->abort();
        currentReply->deleteLater();
        currentReply = nullptr;
    }
}

void TTSManager::stopAudioSink()
{
    m_ignoreAudioIdle = true;
    m_streamFeedScheduled = false;
    m_streamEndScheduled = false;
    m_streamPush = nullptr;
    m_streamWritten = 0;
    m_restartingStream = false;
    m_inStreamFeed = false;
    if (audioSink) {
        audioSink->stop();
        delete audioSink;
        audioSink = nullptr;
    }
    if (audioBuffer) {
        delete audioBuffer;
        audioBuffer = nullptr;
    }
    m_ignoreAudioIdle = false;
}

QUrl TTSManager::buildBaseUrl() const
{
    QUrl url;
    url.setScheme("http");
    url.setHost(serverHost);
    url.setPort(serverPort);
    return url;
}

void TTSManager::applyRequestTimeout(QNetworkRequest& request) const
{
    if (requestTimeoutMs > 0) {
        request.setTransferTimeout(requestTimeoutMs);
    }
}

QUrlQuery TTSManager::buildQueryFromParams(const TTSRequestParams& params) const
{
    QUrlQuery query;
    query.addQueryItem("text", params.text);
    query.addQueryItem("text_lang", params.textLang);
    query.addQueryItem("ref_audio_path", params.refAudioPath);

    if (!params.auxRefAudioPaths.isEmpty()) {
        query.addQueryItem("aux_ref_audio_paths", params.auxRefAudioPaths.join(","));
    }

    query.addQueryItem("prompt_lang", params.promptLang);
    query.addQueryItem("prompt_text", params.promptText);
    query.addQueryItem("top_k", QString::number(params.topK));
    query.addQueryItem("top_p", QString::number(params.topP));
    query.addQueryItem("temperature", QString::number(params.temperature));
    query.addQueryItem("text_split_method", params.textSplitMethod);
    query.addQueryItem("batch_size", QString::number(params.batchSize));
    query.addQueryItem("batch_threshold", QString::number(params.batchThreshold));
    query.addQueryItem("split_bucket", params.splitBucket ? "true" : "false");
    query.addQueryItem("speed_factor", QString::number(params.speedFactor));
    query.addQueryItem("fragment_interval", QString::number(params.fragmentInterval));
    query.addQueryItem("seed", QString::number(params.seed));
    query.addQueryItem("media_type", params.mediaType);
    query.addQueryItem("streaming_mode", m_streaming ? "true" : "false");
    query.addQueryItem("parallel_infer", params.parallelInfer ? "true" : "false");
    query.addQueryItem("repetition_penalty", QString::number(params.repetitionPenalty));
    query.addQueryItem("sample_steps", QString::number(params.sampleSteps));
    query.addQueryItem("super_sampling", params.superSampling ? "true" : "false");

    return query;
}

QJsonObject TTSManager::buildJsonFromParams(const TTSRequestParams& params) const
{
    QJsonObject json;
    json["text"] = params.text;
    json["text_lang"] = params.textLang;
    json["ref_audio_path"] = params.refAudioPath;

    QJsonArray auxPaths;
    if (!params.auxRefAudioPaths.isEmpty()) {
        for (const QString& path : params.auxRefAudioPaths) {
            auxPaths.append(path);
        }
    }
    json["aux_ref_audio_paths"] = auxPaths;

    json["prompt_lang"] = params.promptLang;
    json["prompt_text"] = params.promptText;
    json["top_k"] = params.topK;
    json["top_p"] = params.topP;
    json["temperature"] = params.temperature;
    json["text_split_method"] = params.textSplitMethod;
    json["batch_size"] = params.batchSize;
    json["batch_threshold"] = params.batchThreshold;
    json["split_bucket"] = params.splitBucket;
    json["speed_factor"] = params.speedFactor;
    json["fragment_interval"] = params.fragmentInterval;
    json["seed"] = params.seed;
    json["media_type"] = params.mediaType;
    json["streaming_mode"] = m_streaming;
    json["parallel_infer"] = params.parallelInfer;
    json["repetition_penalty"] = params.repetitionPenalty;
    json["sample_steps"] = params.sampleSteps;
    json["super_sampling"] = params.superSampling;

	// 输出构建的文本
	FINE_DEBUG_OUTPUT("[TTS Operation]Generate text: " + params.text);

    return json;
}

QString TTSManager::rewriteRefAudioPath(const QString& path) const
{
    if (!m_minimalBackend || path.isEmpty()) {
        return path;
    }
    const QFileInfo info(path);
    if (info.isAbsolute()) {
        return path;
    }
    QString normalized = path;
    normalized.replace(QLatin1Char('\\'), QLatin1Char('/'));
    if (normalized.startsWith(QLatin1String("../gpt-sovits/"))) {
        return path;
    }
    while (normalized.startsWith(QLatin1Char('/'))) {
        normalized.remove(0, 1);
    }
    return QStringLiteral("../gpt-sovits/") + normalized;
}

QJsonObject TTSManager::buildMinimalJsonFromParams(const TTSRequestParams& params) const
{
    QJsonObject json;
    json["input"] = params.text;
    json["voice"] = m_voice;
    json["model"] = QStringLiteral("gpt-sovits-v2");
    json["response_format"] = QStringLiteral("wav");
    json["text_lang"] = params.textLang;
    json["speed"] = params.speedFactor;
    json["top_k"] = params.topK;
    json["top_p"] = params.topP;
    json["temperature"] = params.temperature;
    json["pause_length"] = params.fragmentInterval;
    json["ref_audio"] = rewriteRefAudioPath(params.refAudioPath);
    json["ref_text"] = params.promptText;
    json["ref_lang"] = params.promptLang;
    FINE_DEBUG_OUTPUT("[TTS Operation]Generate text: " + params.text);
    return json;
}

bool TTSManager::isTtsReplyPath(const QString& path) const
{
    return path == QLatin1String("/tts") || path == QLatin1String("/v1/audio/speech");
}

void TTSManager::requestTTSGet(const TTSRequestParams& params)
{
    requestQueue.enqueue(QueuedRequest(QueuedRequest::TTSGet, params));
    processNextRequest();
}

void TTSManager::requestTTSPost(const TTSRequestParams& params)
{
    requestQueue.enqueue(QueuedRequest(QueuedRequest::TTSPost, params));
    processNextRequest();
}

void TTSManager::sendControlCommand(const QString& command)
{
    requestQueue.enqueue(QueuedRequest(QueuedRequest::ControlCommand, command));
    processNextRequest();
}

void TTSManager::setGPTWeights(const QString& weightsPath)
{
    requestQueue.enqueue(QueuedRequest(QueuedRequest::SetGPTWeights, weightsPath, true));
    processNextRequest();
}

void TTSManager::setSovitsWeights(const QString& weightsPath)
{
    requestQueue.enqueue(QueuedRequest(QueuedRequest::SetSovitsWeights, weightsPath, true));
    processNextRequest();
}

void TTSManager::warmup(const TTSRequestParams& params)
{
    TTSRequestParams warm = params;
    warm.text = QStringLiteral("老师好。");
    warm.emotion.clear();
    if (m_minimalBackend) {
        requestQueue.enqueue(QueuedRequest(QueuedRequest::WarmupTTS, warm));
        FINE_DEBUG_OUTPUT("[TTS Operation]Warmup queued (short /v1/audio/speech)");
    }
    else {
        if (!params.refAudioPath.isEmpty()) {
            requestQueue.enqueue(QueuedRequest(QueuedRequest::SetReferAudio, params.refAudioPath, true));
        }
        requestQueue.enqueue(QueuedRequest(QueuedRequest::WarmupTTS, warm));
        FINE_DEBUG_OUTPUT("[TTS Operation]Warmup queued (set_refer_audio + short /tts)");
    }
    processNextRequest();
}

void TTSManager::beginStreamingReceive()
{
    m_currentReceive = QSharedPointer<StreamSession>::create();
    m_currentReceive->text = currentTtsText;
    m_currentReceive->emotion = currentTtsEmotion;
    m_currentReceive->mediaType = currentMediaType;
}

void TTSManager::attachStreamingReadyRead()
{
    if (!m_streaming || m_currentIsWarmup || !currentReply) {
        return;
    }
    beginStreamingReceive();
    connect(currentReply, &QNetworkReply::readyRead, this, &TTSManager::onTtsReadyRead);
}

void TTSManager::onTtsReadyRead()
{
    if (!currentReply || m_currentIsWarmup || !m_currentReceive) {
        return;
    }
    m_currentReceive->raw.append(currentReply->readAll());
    consumeReceiveBuffer();
}

void TTSManager::onNetworkReplyFinished()
{
    QNetworkReply* reply = qobject_cast<QNetworkReply*>(sender());
    if (!reply || reply != currentReply) {
        // 如果不是当前请求的回复，忽略并清理
        if (reply) {
            reply->deleteLater();
        }
        return;
    }

    const bool isTts = isTtsReplyPath(reply->url().path());
    const bool warmup = m_currentIsWarmup;
    if (isTts) {
        if (reply->error() != QNetworkReply::NoError) {
            FINE_DEBUG_OUTPUT(QString("[Latency] TTS RTT: %1 ms (%2error)")
                .arg(m_ttsRequestTimer.elapsed())
                .arg(warmup ? QStringLiteral("warmup ") : QString()));
        }
        else {
            FINE_DEBUG_OUTPUT(QString("[Latency] TTS RTT: %1 ms%2")
                .arg(m_ttsRequestTimer.elapsed())
                .arg(warmup ? QStringLiteral(" (warmup)") : QString()));
        }
    }

    if (warmup) {
        if (reply->error() != QNetworkReply::NoError) {
            ERROR_DEBUG_OUTPUT("[TTS Operation]Warmup failed: " + reply->errorString());
        }
        else {
            FINE_DEBUG_OUTPUT("[TTS Operation]Warmup complete");
        }
        m_currentReceive.clear();
        cleanupCurrentReply();
        isProcessingRequest = false;
        processNextRequest();
        return;
    }

    if (isTts) {
        QString errorMsg;
        const bool httpError = reply->error() != QNetworkReply::NoError;
        if (httpError) {
            errorMsg = reply->errorString();
            if (reply->error() == QNetworkReply::TimeoutError
                || reply->error() == QNetworkReply::OperationCanceledError) {
                errorMsg = QString("TTS request timed out after %1 ms").arg(requestTimeoutMs);
            }
        }
        if (m_streaming && m_currentReceive) {
            m_currentReceive->raw.append(reply->readAll());
            finishStreamingReceive(reply, httpError, errorMsg);
        }
        else {
            enqueueTtsPlaybackFromReply(reply, httpError, errorMsg);
        }
        cleanupCurrentReply();
        isProcessingRequest = false;
        processNextRequest();
        tryDeliverPlayback();
        return;
    }

    cleanupCurrentReply();
    isProcessingRequest = false;
    processNextRequest();
}

void TTSManager::consumeReceiveBuffer()
{
    if (!m_currentReceive || m_currentReceive->jsonError) {
        return;
    }
    const QSharedPointer<StreamSession> session = m_currentReceive;

    if (!session->headerParsed) {
        if (session->raw.isEmpty()) {
            return;
        }
        if (session->raw.startsWith('{')) {
            const QJsonDocument doc = QJsonDocument::fromJson(session->raw);
            if (doc.isObject()) {
                session->jsonError = true;
                QString msg = doc.object().value(QStringLiteral("message")).toString();
                if (msg.isEmpty()) {
                    msg = QString::fromUtf8(session->raw);
                }
                enqueueStreamError(session, msg);
            }
            return;
        }
        WavHeaderInfo header;
        if (!parseWavHeader(session->raw, &header)) {
            return;
        }
        session->headerParsed = true;
        session->sampleRate = header.sampleRate;
        session->channelCount = header.channelCount;
        session->bitsPerSample = header.bitsPerSample;
        session->pcmOffset = header.pcmOffset;
        FINE_DEBUG_OUTPUT(QString("[TTS Operation]Stream WAV header: sample rate: %1 | channel num: %2 | bits per sample: %3")
            .arg(session->sampleRate)
            .arg(session->channelCount)
            .arg(session->bitsPerSample));
    }

    const int available = session->raw.size() - session->pcmOffset;
    if (available <= 0) {
        return;
    }
    const int frameSize = qMax(1, session->channelCount * (session->bitsPerSample / 8));
    const int aligned = available - (available % frameSize);
    if (aligned <= 0) {
        return;
    }
    const QByteArray pcm = session->raw.mid(session->pcmOffset, aligned);
    session->raw = session->raw.mid(session->pcmOffset + aligned);
    session->pcmOffset = 0;
    appendSessionPcm(session, pcm);
}

void TTSManager::appendSessionPcm(const QSharedPointer<StreamSession>& session, const QByteArray& pcm)
{
    if (!session || pcm.isEmpty()) {
        return;
    }
    if (!session->firstPcmSeen) {
        session->firstPcmSeen = true;
        FINE_DEBUG_OUTPUT(QString("[Latency] TTS first packet: %1 ms (%2 bytes)")
            .arg(m_ttsRequestTimer.elapsed())
            .arg(pcm.size()));
    }
    session->pcm.append(pcm);
    if (m_playingAudio && m_deliveredStream == session) {
        feedStreamAudio();
    }
    if (!session->enqueued) {
        session->enqueued = true;
        enqueueStreamSession(session);
        tryDeliverPlayback();
    }
}

void TTSManager::enqueueStreamSession(const QSharedPointer<StreamSession>& session)
{
    ReadyPlayback item;
    item.isStream = true;
    item.stream = session;
    item.text = session->text;
    item.emotion = session->emotion;
    item.mediaType = session->mediaType;
    m_readyPlayback.enqueue(item);
}

void TTSManager::enqueueStreamError(const QSharedPointer<StreamSession>& session, const QString& errorString)
{
    if (!session || session->enqueued) {
        return;
    }
    session->enqueued = true;
    ReadyPlayback item;
    item.isError = true;
    item.text = session->text;
    item.emotion = session->emotion;
    item.errorString = errorString;
    m_readyPlayback.enqueue(item);
}

void TTSManager::finishStreamingReceive(QNetworkReply* reply, bool httpError, const QString& errorString)
{
    Q_UNUSED(reply);
    consumeReceiveBuffer();
    const QSharedPointer<StreamSession> session = m_currentReceive;
    m_currentReceive.clear();
    if (!session) {
        return;
    }

    if (session->jsonError) {
        return;
    }

    if (httpError && !session->firstPcmSeen) {
        enqueueStreamError(session, errorString);
        return;
    }

    if (!session->firstPcmSeen) {
        if (session->raw.startsWith('{')) {
            const QJsonDocument doc = QJsonDocument::fromJson(session->raw);
            QString msg = errorString;
            if (doc.isObject()) {
                const QString parsed = doc.object().value(QStringLiteral("message")).toString();
                if (!parsed.isEmpty()) {
                    msg = parsed;
                }
            }
            enqueueStreamError(session, msg.isEmpty() ? QStringLiteral("TTS stream returned JSON error") : msg);
            return;
        }
        enqueueStreamError(session, errorString.isEmpty()
            ? QStringLiteral("TTS stream ended before first audio")
            : errorString);
        return;
    }

    if (httpError) {
        ERROR_DEBUG_OUTPUT("[TTS Operation]Stream HTTP error after first packet: " + errorString);
    }
    session->complete = true;
    if (m_playingAudio && m_deliveredStream == session) {
        feedStreamAudio();
    }
}

void TTSManager::enqueueTtsPlaybackFromReply(QNetworkReply* reply, bool httpError, const QString& errorString)
{
    ReadyPlayback item;
    item.text = currentTtsText;
    item.emotion = currentTtsEmotion;
    item.mediaType = currentMediaType;

    if (httpError) {
        item.isError = true;
        item.errorString = errorString;
        m_readyPlayback.enqueue(item);
        return;
    }

    if (reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() == 200) {
        QByteArray audioData = reply->readAll();

        if (audioData.startsWith('{') && audioData.contains("message")) {
            QJsonDocument doc = QJsonDocument::fromJson(audioData);
            if (doc.isObject()) {
                item.isError = true;
                item.errorString = doc.object()["message"].toString();
                m_readyPlayback.enqueue(item);
                return;
            }
        }

        item.audioData = audioData;
        m_readyPlayback.enqueue(item);
        return;
    }

    QByteArray errorData = reply->readAll();
    QString errorMsg = QString::fromUtf8(errorData);
    if (errorData.startsWith('{')) {
        QJsonDocument doc = QJsonDocument::fromJson(errorData);
        if (doc.isObject()) {
            errorMsg = doc.object()["message"].toString();
        }
    }
    item.isError = true;
    item.errorString = errorMsg;
    m_readyPlayback.enqueue(item);
}

void TTSManager::tryDeliverPlayback()
{
    if (m_awaitingPlayback || m_readyPlayback.isEmpty()) {
        return;
    }
    ReadyPlayback item = m_readyPlayback.dequeue();
    m_awaitingPlayback = true;
    if (item.isError) {
        emit ttsError(item.errorString, item.text, item.emotion);
    }
    else if (item.isStream) {
        m_deliveredStream = item.stream;
        emit ttsStreamReady(item.text, item.emotion);
    }
    else {
        emit ttsFinished(item.audioData, item.mediaType, item.text, item.emotion);
    }
}

void TTSManager::notifyPlaybackFinished()
{
    if (!m_awaitingPlayback) {
        return;
    }
    m_awaitingPlayback = false;
    m_playingAudio = false;
    m_playbackGeneration++;
    m_deliveredStream.clear();
    stopAudioSink();
    tryDeliverPlayback();
}

void TTSManager::finishAudioPlayback()
{
    if (!m_awaitingPlayback) {
        return;
    }
    emit playbackEnded();
    notifyPlaybackFinished();
}

bool TTSManager::isPlayingAudio() const
{
    return m_playingAudio || m_awaitingPlayback;
}

void TTSManager::interruptPlayback()
{
    m_playbackGeneration++;
    requestQueue.clear();
    m_readyPlayback.clear();
    m_currentReceive.clear();
    m_deliveredStream.clear();
    cleanupCurrentReply();
    isProcessingRequest = false;
    stopAudioSink();
    m_playingAudio = false;
    m_awaitingPlayback = false;
    m_restartingStream = false;
    FINE_DEBUG_OUTPUT("[TTS Operation]Playback interrupted");
}

void TTSManager::scheduleStreamFeed(int delayMs)
{
    if (m_streamFeedScheduled || !m_playingAudio) {
        return;
    }
    m_streamFeedScheduled = true;
    const int gen = m_playbackGeneration;
    QTimer::singleShot(qMax(0, delayMs), this, [this, gen]() {
        if (gen != m_playbackGeneration) {
            return;
        }
        m_streamFeedScheduled = false;
        if (!m_playingAudio) {
            return;
        }
        feedStreamAudio();
    });
}

void TTSManager::restartStreamSink()
{
    if (!audioSink || !m_playingAudio || m_restartingStream) {
        return;
    }
    // Qt 6.5.3：Idle 时 IAudioClient 已 Stop。直接 start() 会先 close 丢掉缓冲。
    // 先 stop 回到 Stopped，再 start 推流，未写入的 PCM 仍留在写指针之后。
    m_restartingStream = true;
    m_ignoreAudioIdle = true;
    m_streamPush = nullptr;
    audioSink->stop();
    m_streamPush = audioSink->start();
    m_ignoreAudioIdle = false;
    m_restartingStream = false;
    if (!m_streamPush) {
        ERROR_DEBUG_OUTPUT("[TTS Operation]Stream push restart failed");
    }
}

void TTSManager::feedStreamAudio()
{
    if (m_inStreamFeed || !m_playingAudio || !m_deliveredStream || !audioSink) {
        return;
    }
    m_inStreamFeed = true;

    const QByteArray& pcm = m_deliveredStream->pcm;
    if (m_streamWritten > pcm.size()) {
        m_streamWritten = pcm.size();
    }
    const qint64 unwritten = pcm.size() - m_streamWritten;
    const QAudio::State state = m_streamPush ? audioSink->state() : QAudio::StoppedState;
    const bool idle = !m_streamPush
        || state == QAudio::IdleState
        || state == QAudio::StoppedState;
    // 刚 start() 是 Idle 且 error 为 NoError，可以直接 write。
    // 欠载后 error 为 UnderrunError，IAudioClient 已 Stop，必须先停再开。
    // 欠载回调推迟到 stateChanged 返回之后，那时 error 已经写上。
    const bool needRestart = !m_streamPush
        || state == QAudio::StoppedState
        || audioSink->error() == QAudio::UnderrunError;

    if (unwritten <= 0) {
        m_inStreamFeed = false;
        if (m_deliveredStream->complete && idle) {
            scheduleStreamPlaybackEnd();
        }
        return;
    }

    if (idle && needRestart) {
        restartStreamSink();
        if (!m_streamPush) {
            m_inStreamFeed = false;
            scheduleStreamFeed(30);
            return;
        }
    }

    const int frameSize = qMax(1, m_deliveredStream->channelCount
        * qMax(1, m_deliveredStream->bitsPerSample / 8));
    qint64 room = audioSink->bytesFree();
    qint64 n = qMin(unwritten, room);
    if (frameSize > 1) {
        n -= n % frameSize;
    }
    if (n <= 0) {
        if (unwritten < frameSize) {
            m_streamWritten = pcm.size();
            m_inStreamFeed = false;
            if (m_deliveredStream->complete && idle) {
                scheduleStreamPlaybackEnd();
            }
            return;
        }
        m_inStreamFeed = false;
        scheduleStreamFeed(15);
        return;
    }

    qint64 wroteThisCall = 0;
    bool writeFailed = false;
    while (m_streamWritten < pcm.size()) {
        room = audioSink->bytesFree();
        n = qMin(static_cast<qint64>(pcm.size()) - m_streamWritten, room);
        if (frameSize > 1) {
            n -= n % frameSize;
        }
        if (n <= 0) {
            if (pcm.size() - m_streamWritten < frameSize) {
                m_streamWritten = pcm.size();
            }
            break;
        }
        const qint64 written = m_streamPush->write(
            pcm.constData() + static_cast<qsizetype>(m_streamWritten), n);
        if (written <= 0) {
            writeFailed = true;
            break;
        }
        m_streamWritten += written;
        wroteThisCall += written;
        if (written < n) {
            break;
        }
    }
    if (writeFailed && wroteThisCall == 0) {
        m_streamPush = nullptr;
        m_inStreamFeed = false;
        scheduleStreamFeed(30);
        return;
    }
    const bool more = m_streamWritten < pcm.size();
    const QAudio::State after = audioSink ? audioSink->state() : QAudio::StoppedState;
    m_inStreamFeed = false;
    if (!more) {
        if (m_deliveredStream && m_deliveredStream->complete
            && (after == QAudio::IdleState || after == QAudio::StoppedState)) {
            scheduleStreamPlaybackEnd();
        }
        return;
    }
    const bool stalled = after == QAudio::IdleState || after == QAudio::StoppedState;
    scheduleStreamFeed(stalled ? 0 : 10);
}

void TTSManager::scheduleStreamPlaybackEnd()
{
    if (m_streamEndScheduled || !m_deliveredStream || !m_playingAudio || !audioSink) {
        return;
    }
    if (!m_deliveredStream->complete) {
        return;
    }
    if (m_streamWritten < m_deliveredStream->pcm.size()) {
        return;
    }
    const QAudio::State state = audioSink->state();
    if (state != QAudio::IdleState && state != QAudio::StoppedState) {
        return;
    }

    const double totalSec = pcmDurationSec(
        m_deliveredStream->pcm.size(),
        m_deliveredStream->sampleRate,
        m_deliveredStream->channelCount,
        m_deliveredStream->bitsPerSample);
    int remainMs = 80;
    if (totalSec > 0 && m_streamPlayTimer.isValid()) {
        remainMs = static_cast<int>(totalSec * 1000.0)
            - static_cast<int>(m_streamPlayTimer.elapsed()) + 80;
    }
    if (remainMs < 0) {
        remainMs = 0;
    }
    m_streamEndScheduled = true;
    const int gen = m_playbackGeneration;
    QTimer::singleShot(remainMs, this, [this, gen]() {
        if (gen != m_playbackGeneration) {
            return;
        }
        finishAudioPlayback();
    });
}

double TTSManager::pcmDurationSec(qint64 bytes, int sampleRate, int channelCount, int bitsPerSample) const
{
    if (bytes <= 0 || sampleRate <= 0 || channelCount <= 0 || bitsPerSample <= 0) {
        return -1;
    }
    return static_cast<double>(bytes)
        / (static_cast<double>(sampleRate) * channelCount * (bitsPerSample / 8.0));
}

double TTSManager::startStreamPlayback()
{
    if (!m_deliveredStream || m_deliveredStream->pcm.isEmpty()) {
        QTimer::singleShot(0, this, [this]() {
            finishAudioPlayback();
        });
        return -1;
    }
    const QSharedPointer<StreamSession> session = m_deliveredStream;

    stopAudioSink();

    QAudioFormat format;
    format.setSampleRate(session->sampleRate);
    format.setChannelCount(session->channelCount);
    format.setSampleFormat(QAudioFormat::Int16);

    QAudioDevice audioDevice = QMediaDevices::defaultAudioOutput();
    if (!audioDevice.isFormatSupported(format)) {
        ERROR_DEBUG_OUTPUT("[TTS Operation]Default format not supported, trying to use preferred format");
        format = audioDevice.preferredFormat();
    }

    audioSink = new QAudioSink(audioDevice, format, this);
    audioSink->setBufferSize(qMax(8192, session->sampleRate * session->channelCount * 2));
    connect(audioSink, &QAudioSink::stateChanged, this, [this](QAudio::State state) {
        if (m_ignoreAudioIdle || !m_playingAudio || m_restartingStream || m_inStreamFeed) {
            return;
        }
        if (state != QAudio::IdleState && state != QAudio::StoppedState) {
            return;
        }
        if (!m_deliveredStream) {
            return;
        }
        if (m_streamWritten < m_deliveredStream->pcm.size()) {
            // 离开 stateChanged 再 stop/start，避免在 Qt 回调里拆掉声卡。
            scheduleStreamFeed(0);
            return;
        }
        if (m_deliveredStream->complete) {
            scheduleStreamPlaybackEnd();
        }
    });

    m_playingAudio = true;
    ++m_playbackGeneration;
    m_streamWritten = 0;
    m_streamFeedScheduled = false;
    m_streamEndScheduled = false;
    m_streamPlayTimer.start();
    m_ignoreAudioIdle = true;
    m_streamPush = audioSink->start();
    m_ignoreAudioIdle = false;
    if (!m_streamPush) {
        ERROR_DEBUG_OUTPUT("[TTS Operation]Stream push start failed");
        QTimer::singleShot(0, this, [this]() {
            finishAudioPlayback();
        });
        return -1;
    }
    feedStreamAudio();

    const double duration = pcmDurationSec(
        session->pcm.size(), session->sampleRate, session->channelCount, session->bitsPerSample);
    return session->complete ? duration : -1;
}

double TTSManager::playAudio(const QByteArray& audioData)
{
    if (audioData.isEmpty()) {
        notifyPlaybackFinished();
        return -1;
    }

    WavPcmInfo wav;
    QByteArray pcm = audioData;
    int sampleRate = 32000;
    int channelCount = 1;
    double duration = -1;
    if (extractWavPcm(audioData, &wav)) {
        pcm = wav.pcm;
        sampleRate = wav.sampleRate;
        channelCount = wav.channelCount;
        duration = wav.durationSec;
    }
    else {
        ERROR_DEBUG_OUTPUT("[TTS Operation]WAV parse failed, playing bytes as raw PCM");
    }

    // 队列播下一条时才 stop；此时上一条应已结束
    stopAudioSink();

    QAudioFormat format;
    format.setSampleRate(sampleRate);
    format.setChannelCount(channelCount);
    format.setSampleFormat(QAudioFormat::Int16);

    QAudioDevice audioDevice = QMediaDevices::defaultAudioOutput();
    if (!audioDevice.isFormatSupported(format)) {
        ERROR_DEBUG_OUTPUT("[TTS Operation]Default format not supported, trying to use preferred format");
        format = audioDevice.preferredFormat();
    }

    audioBuffer = new QBuffer(this);
    audioBuffer->setData(pcm);
    audioBuffer->open(QIODevice::ReadOnly);

    audioSink = new QAudioSink(audioDevice, format, this);
    connect(audioSink, &QAudioSink::stateChanged, this, [this](QAudio::State state) {
        if (m_ignoreAudioIdle || !m_playingAudio) {
            return;
        }
        if (state == QAudio::IdleState || state == QAudio::StoppedState) {
            notifyPlaybackFinished();
        }
    });

    m_playingAudio = true;
    audioSink->start(audioBuffer);
    m_ignoreAudioIdle = false;

    const int fallbackMs = duration > 0 ? static_cast<int>(duration * 1000.0) + 500 : 10000;
    const int gen = ++m_playbackGeneration;
    QTimer::singleShot(fallbackMs, this, [this, gen]() {
        if (gen != m_playbackGeneration) {
            return;
        }
        notifyPlaybackFinished();
    });
    return duration;
}

bool TTSManager::saveAudioToFile(const QByteArray& audioData, const QString& filePath)
{
    QFile file(filePath);
    if (file.open(QIODevice::WriteOnly)) {
        file.write(audioData);
        file.close();
        return true;
    }
    return false;
}

bool TTSManager::parseWavHeader(const QByteArray& wav, WavHeaderInfo* out) const
{
    if (!out || wav.size() < 12) {
        return false;
    }
    const char* data = wav.constData();
    if (memcmp(data, "RIFF", 4) != 0 || memcmp(data + 8, "WAVE", 4) != 0) {
        return false;
    }

    int sampleRate = 0;
    int channelCount = 0;
    int bitsPerSample = 0;
    int pcmOffset = -1;
    quint32 pcmSize = 0;

    int offset = 12;
    while (offset + 8 <= wav.size()) {
        char chunkId[4];
        quint32 chunkSize = 0;
        memcpy(chunkId, data + offset, 4);
        memcpy(&chunkSize, data + offset + 4, 4);
        const int payload = offset + 8;
        if (payload > wav.size()) {
            break;
        }
        if (memcmp(chunkId, "fmt ", 4) == 0 && chunkSize >= 16 && payload + 16 <= wav.size()) {
            quint16 audioFormat = 0;
            quint16 channels = 0;
            quint32 rate = 0;
            quint16 bits = 0;
            memcpy(&audioFormat, data + payload, 2);
            memcpy(&channels, data + payload + 2, 2);
            memcpy(&rate, data + payload + 4, 4);
            memcpy(&bits, data + payload + 14, 2);
            Q_UNUSED(audioFormat);
            channelCount = channels;
            sampleRate = static_cast<int>(rate);
            bitsPerSample = bits;
        }
        else if (memcmp(chunkId, "data", 4) == 0) {
            pcmOffset = payload;
            pcmSize = chunkSize;
            break;
        }
        else {
            if (payload + static_cast<int>(chunkSize) > wav.size()) {
                return false;
            }
        }
        offset += 8 + static_cast<int>(chunkSize);
        if (chunkSize & 1) {
            offset += 1;
        }
    }

    if (pcmOffset < 0 || sampleRate <= 0 || channelCount <= 0 || bitsPerSample <= 0) {
        return false;
    }
    out->sampleRate = sampleRate;
    out->channelCount = channelCount;
    out->bitsPerSample = bitsPerSample;
    out->pcmOffset = pcmOffset;
    out->pcmSize = pcmSize;
    return true;
}

bool TTSManager::extractWavPcm(const QByteArray& wav, WavPcmInfo* out) const
{
    if (!out) {
        return false;
    }
    WavHeaderInfo header;
    if (!parseWavHeader(wav, &header)) {
        return false;
    }
    const int available = wav.size() - header.pcmOffset;
    int bytes = 0;
    if (header.pcmSize == 0 || static_cast<int>(header.pcmSize) < available) {
        bytes = available;
    }
    else {
        bytes = qMin(static_cast<int>(header.pcmSize), available);
    }
    if (bytes <= 0) {
        return false;
    }

    out->pcm = wav.mid(header.pcmOffset, bytes);
    out->sampleRate = header.sampleRate;
    out->channelCount = header.channelCount;
    out->bitsPerSample = header.bitsPerSample;
    out->durationSec = pcmDurationSec(bytes, header.sampleRate, header.channelCount, header.bitsPerSample);

    FINE_DEBUG_OUTPUT(QString("[TTS Operation]WAV file information: ")
        + "sample rate: " + QString::number(header.sampleRate)
        + "| channel num: " + QString::number(header.channelCount)
        + "| bits per sample: " + QString::number(header.bitsPerSample)
        + "| data size:" + QString::number(bytes)
        + "| duration:" + QString::number(out->durationSec) + " second");
    return true;
}

double TTSManager::getWavDuration(const QByteArray& audioData)
{
    WavPcmInfo info;
    if (!extractWavPcm(audioData, &info)) {
        ERROR_DEBUG_OUTPUT("[TTS Operation]Failed to find data");
        return -1;
    }
    return info.durationSec;
}

void TTSManager::processNextRequest()
{
    // 合成与播放解耦：只挡 HTTP 进行中，不挡正在播放
    if (isProcessingRequest || requestQueue.isEmpty()) {
        return;
    }

    isProcessingRequest = true;
    QueuedRequest request = requestQueue.dequeue();
    m_currentIsWarmup = (request.type == QueuedRequest::WarmupTTS);

    switch (request.type) {
    case QueuedRequest::TTSGet:
        executeTTSGet(request.params);
        break;
    case QueuedRequest::TTSPost:
    case QueuedRequest::WarmupTTS:
        executeTTSPost(request.params);
        break;
    case QueuedRequest::ControlCommand:
        executeControlCommand(request.command);
        break;
    case QueuedRequest::SetGPTWeights:
        executeSetGPTWeights(request.weightsPath);
        break;
    case QueuedRequest::SetSovitsWeights:
        executeSetSovitsWeights(request.weightsPath);
        break;
    case QueuedRequest::SetReferAudio:
        executeSetReferAudio(request.weightsPath);
        break;
    }
}

void TTSManager::executeTTSGet(const TTSRequestParams& params)
{
    if (m_minimalBackend) {
        executeTTSPost(params);
        return;
    }

    QUrl url = buildBaseUrl();
    url.setPath("/tts");
    url.setQuery(buildQueryFromParams(params));

    QNetworkRequest request(url);
    applyRequestTimeout(request);
    currentMediaType = params.mediaType;
    currentTtsText = params.text;
    currentTtsEmotion = params.emotion;

    cleanupCurrentReply();
    m_ttsRequestTimer.restart();
    currentReply = networkManager->get(request);

    connect(currentReply, &QNetworkReply::finished,
        this, &TTSManager::onNetworkReplyFinished);
    attachStreamingReadyRead();
    if (m_streaming && !m_currentIsWarmup && currentReply && currentReply->bytesAvailable() > 0) {
        onTtsReadyRead();
    }
}

void TTSManager::executeTTSPost(const TTSRequestParams& params)
{
    QUrl url = buildBaseUrl();
    url.setPath(m_minimalBackend ? QStringLiteral("/v1/audio/speech") : QStringLiteral("/tts"));

    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    applyRequestTimeout(request);

    const QJsonObject json = m_minimalBackend
        ? buildMinimalJsonFromParams(params)
        : buildJsonFromParams(params);
    QJsonDocument doc(json);
    QByteArray data = doc.toJson();

    currentMediaType = params.mediaType;
    currentTtsText = params.text;
    currentTtsEmotion = params.emotion;

    cleanupCurrentReply();
    m_ttsRequestTimer.restart();
    currentReply = networkManager->post(request, data);

    connect(currentReply, &QNetworkReply::finished,
        this, &TTSManager::onNetworkReplyFinished);
    attachStreamingReadyRead();
    if (m_streaming && !m_currentIsWarmup && currentReply && currentReply->bytesAvailable() > 0) {
        onTtsReadyRead();
    }
}

void TTSManager::executeControlCommand(const QString& command)
{
    QUrl url = buildBaseUrl();
    url.setPath("/control");

    QUrlQuery query;
    query.addQueryItem("command", command);
    url.setQuery(query);

    QNetworkRequest request(url);
    cleanupCurrentReply();
    currentReply = networkManager->get(request);

    connect(currentReply, &QNetworkReply::finished, [this]() {
        if (currentReply->error() == QNetworkReply::NoError) {
            emit commandFinished(true, "Command executed successfully");
        }
        else {
            emit commandFinished(false, currentReply->errorString());
        }

        // 清理并处理下一个请求
        cleanupCurrentReply();
        isProcessingRequest = false;
        processNextRequest();
        });
}

void TTSManager::executeSetGPTWeights(const QString& weightsPath)
{
    QUrl url = buildBaseUrl();
    url.setPath("/set_gpt_weights");

    QUrlQuery query;
    query.addQueryItem("weights_path", weightsPath);
    url.setQuery(query);

    QNetworkRequest request(url);
    applyRequestTimeout(request);
    cleanupCurrentReply();
    currentReply = networkManager->get(request);

    connect(currentReply, &QNetworkReply::finished, [this]() {
        if (!currentReply) {
            emit modelSwitched(false, "GPT weight request aborted");
            isProcessingRequest = false;
            processNextRequest();
            return;
        }
        if (currentReply->error() == QNetworkReply::NoError) {
            QByteArray data = currentReply->readAll();
            if (data.contains("success")) {
                emit modelSwitched(true, "GPT model switched successfully");
            }
            else {
                emit modelSwitched(false, QString::fromUtf8(data));
            }
        }
        else {
            QString errorMsg = currentReply->errorString();
            if (currentReply->error() == QNetworkReply::TimeoutError
                || currentReply->error() == QNetworkReply::OperationCanceledError) {
                errorMsg = QString("GPT weight request timed out after %1 ms").arg(requestTimeoutMs);
            }
            emit modelSwitched(false, errorMsg);
        }

        cleanupCurrentReply();
        isProcessingRequest = false;
        processNextRequest();
        });
}

void TTSManager::executeSetSovitsWeights(const QString& weightsPath)
{
    QUrl url = buildBaseUrl();
    url.setPath("/set_sovits_weights");

    QUrlQuery query;
    query.addQueryItem("weights_path", weightsPath);
    url.setQuery(query);

    QNetworkRequest request(url);
    applyRequestTimeout(request);
    cleanupCurrentReply();
    currentReply = networkManager->get(request);

    connect(currentReply, &QNetworkReply::finished, [this]() {
        if (!currentReply) {
            emit modelSwitched(false, "Sovits weight request aborted");
            isProcessingRequest = false;
            processNextRequest();
            return;
        }
        if (currentReply->error() == QNetworkReply::NoError) {
            QByteArray data = currentReply->readAll();
            if (data.contains("success")) {
                emit modelSwitched(true, "Sovits model switched successfully");
            }
            else {
                emit modelSwitched(false, QString::fromUtf8(data));
            }
        }
        else {
            QString errorMsg = currentReply->errorString();
            if (currentReply->error() == QNetworkReply::TimeoutError
                || currentReply->error() == QNetworkReply::OperationCanceledError) {
                errorMsg = QString("Sovits weight request timed out after %1 ms").arg(requestTimeoutMs);
            }
            emit modelSwitched(false, errorMsg);
        }

        cleanupCurrentReply();
        isProcessingRequest = false;
        processNextRequest();
        });
}

void TTSManager::executeSetReferAudio(const QString& audioPath)
{
    QUrl url = buildBaseUrl();
    url.setPath("/set_refer_audio");

    QUrlQuery query;
    query.addQueryItem("refer_audio_path", audioPath);
    url.setQuery(query);

    QNetworkRequest request(url);
    applyRequestTimeout(request);
    cleanupCurrentReply();
    currentReply = networkManager->get(request);

    connect(currentReply, &QNetworkReply::finished, [this]() {
        if (!currentReply) {
            ERROR_DEBUG_OUTPUT("[TTS Operation]set_refer_audio aborted");
            isProcessingRequest = false;
            processNextRequest();
            return;
        }
        if (currentReply->error() == QNetworkReply::NoError) {
            FINE_DEBUG_OUTPUT("[TTS Operation]set_refer_audio success");
        }
        else {
            ERROR_DEBUG_OUTPUT("[TTS Operation]set_refer_audio failed: " + currentReply->errorString());
        }

        cleanupCurrentReply();
        isProcessingRequest = false;
        processNextRequest();
        });
}
