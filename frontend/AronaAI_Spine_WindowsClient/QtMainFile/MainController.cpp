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

#include "MainController.h"
#include "SpokenTextSplitter.h"
#include "ScreenCapture.h"
#include "ComputerUseExecutor.h"
#include <QJsonObject>
#include <QList>
#include <QTimer>
#include <QWidget>

namespace {
constexpr int kPatMinDurationMs = 2000;
constexpr int kPatCooldownMs = 10000;
constexpr int kSilentInteractEmotionMs = 2000;
}

MainController::MainController(MainWidget* mainWidget, TTSManager* ttsManager, AudioRecorder* audioRecorder, TencentSpeechRecognizer* speechRecognizer, WebSocketController* webSocketController, UserInputWidget* userInputWidget)
    : m_mainWidget(mainWidget)
    , m_ttsManager(ttsManager)
    , m_audioRecorder(audioRecorder)
    , m_tencentRecognizer(speechRecognizer)
    , m_webSocketController(webSocketController)
    , m_userInputWidget(userInputWidget)
{
    // 进行TTS初始化
    // 构建TTS请求参数
    ttsRequestParams.text = "";  // 要合成的文本
    ttsRequestParams.textLang = GET_STRING_FROM_JSON(_global_config, "tts", "text_lang");    // 文本语言
    ttsRequestParams.refAudioPath = GET_STRING_FROM_JSON(_global_config, "tts", "ref_audio_path");  // 参考音频路径
    ttsRequestParams.auxRefAudioPaths;   // 辅助参考音频路径
    ttsRequestParams.promptText = GET_STRING_FROM_JSON(_global_config, "tts", "prompt_text");    // 提示文本
    ttsRequestParams.promptLang = GET_STRING_FROM_JSON(_global_config, "tts", "prompt_lang");  // 提示文本语言
    ttsRequestParams.topK = GET_INT_FROM_JSON(_global_config, "tts", "top_k");   // top k采样
    ttsRequestParams.topP = GET_DOUBLE_FROM_JSON(_global_config, "tts", "top_p");  // top p采样
    ttsRequestParams.temperature = GET_DOUBLE_FROM_JSON(_global_config, "tts", "temperature");   // 温度参数
    ttsRequestParams.textSplitMethod = GET_STRING_FROM_JSON(_global_config, "tts", "text_split_method");   // 文本分割方法
    ttsRequestParams.batchSize = GET_INT_FROM_JSON(_global_config, "tts", "batch_size");  // 批处理大小
    ttsRequestParams.batchThreshold = GET_DOUBLE_FROM_JSON(_global_config, "tts", "batch_threshold");   // 批处理阈值
    ttsRequestParams.splitBucket = GET_BOOL_FROM_JSON(_global_config, "tts", "split_bucket");    // 是否分割桶
    ttsRequestParams.speedFactor = GET_DOUBLE_FROM_JSON(_global_config, "tts", "speed_factor");   // 语速因子
    ttsRequestParams.fragmentInterval = GET_DOUBLE_FROM_JSON(_global_config, "tts", "fragment_interval");  // 片段间隔
    ttsRequestParams.seed = GET_INT_FROM_JSON(_global_config, "tts", "seed");  // 随机种子
    ttsRequestParams.parallelInfer = GET_BOOL_FROM_JSON(_global_config, "tts", "parallel_infer");  // 并行推理
    ttsRequestParams.repetitionPenalty = GET_DOUBLE_FROM_JSON(_global_config, "tts", "repetition_penalty");    // 重复惩罚
    ttsRequestParams.sampleSteps = GET_INT_FROM_JSON(_global_config, "tts", "sample_steps");   // 采样步数
    ttsRequestParams.superSampling = GET_BOOL_FROM_JSON(_global_config, "tts", "super_sampling"); // 超采样
    ttsRequestParams.mediaType = "wav";  // 媒体类型
    m_ttsRefMap.loadFromConfig();

    connect(m_ttsManager, &TTSManager::ttsFinished, this, &MainController::onTTSFinished);
    connect(m_ttsManager, &TTSManager::ttsStreamReady, this, &MainController::onTTSStreamReady);
    connect(m_ttsManager, &TTSManager::playbackEnded, this, &MainController::onTtsPlaybackEnded);
    connect(m_ttsManager, &TTSManager::ttsError, this, &MainController::onTTSError);

    m_ttsWeightTimer.start();
    connect(m_ttsManager, &TTSManager::modelSwitched, this,
        [this](bool success, const QString& message) {
            m_ttsModelsLoaded++;
            if (success) {
                FINE_DEBUG_OUTPUT("[TTS Operation]Model set: true, Message: " + message
                    + "(" + QString::number(m_ttsModelsLoaded) + "/2)");
            }
            else {
                ERROR_DEBUG_OUTPUT("[TTS Operation]Model set: false, Message: " + message
                    + "(" + QString::number(m_ttsModelsLoaded) + "/2)");
            }
            if (m_ttsModelsLoaded >= 2) {
                FINE_DEBUG_OUTPUT(QString("[Startup] TTS models ready: %1 ms")
                    .arg(m_ttsWeightTimer.isValid() ? m_ttsWeightTimer.elapsed() : -1));
            }
        });

    const bool reloadWeights = GET_BOOL_FROM_JSON(_global_config, "tts", "reload_weights_on_start");
    if (!m_ttsManager->isMinimalBackend() && reloadWeights) {
        m_ttsManager->setGPTWeights(GET_STRING_FROM_JSON(_global_config, "tts", "gpt_path"));
        m_ttsManager->setSovitsWeights(GET_STRING_FROM_JSON(_global_config, "tts", "sovits_path"));
        FINE_DEBUG_OUTPUT("[Startup] TTS weight switch queued (reload_weights_on_start=true)");
    }
    else if (m_ttsManager->isMinimalBackend()) {
        FINE_DEBUG_OUTPUT("[Startup] Skip TTS weight reload (minimal backend; voices.json weights stay loaded)");
    }
    else {
        FINE_DEBUG_OUTPUT("[Startup] Skip TTS weight reload (reload_weights_on_start=false); yaml weights stay loaded");
    }
    m_ttsManager->warmup(ttsRequestParams);
    FINE_DEBUG_OUTPUT("[Startup] TTS warmup queued, connecting WebSocket without waiting");

    connect(m_audioRecorder, &AudioRecorder::errorOccurred,
        this, &MainController::onAudioError);
    connect(m_audioRecorder, &AudioRecorder::pcmFrameReady,
        this, &MainController::onPcmFrame, Qt::QueuedConnection);
    connect(m_audioRecorder, &AudioRecorder::speechDetected,
        this, &MainController::onSpeechDetected, Qt::QueuedConnection);

    if (m_tencentRecognizer) {
        m_tencentRecognizer->setParent(this);
    }
    connect(m_tencentRecognizer, &TencentSpeechRecognizer::errorOccurred,
        this, &MainController::onRecognizeError);
    connect(m_tencentRecognizer, &TencentSpeechRecognizer::transcriptReceived,
        this, &MainController::onTranscriptReceived);

    QString secretId = GET_STRING_FROM_JSON(_global_config, "tencent_speech_recognizer", "secret_id");
    QString secretKey = GET_STRING_FROM_JSON(_global_config, "tencent_speech_recognizer", "secret_key");
    QString appId = GET_STRING_FROM_JSON(_global_config, "tencent_speech_recognizer", "app_id");
    if (appId.isEmpty()) {
        const int appIdNum = GET_INT_FROM_JSON(_global_config, "tencent_speech_recognizer", "app_id");
        if (appIdNum > 0) {
            appId = QString::number(appIdNum);
        }
    }
    m_tencentRecognizer->setCredentials(secretId, secretKey, appId);
    m_tencentRecognizer->setVadSilenceTime(
        GET_INT_FROM_JSON(_global_config, "tencent_speech_recognizer", "vad_silence_time"));

    connect(m_webSocketController, &WebSocketController::connected,
        this, &MainController::onWebSocketConnected);
    connect(m_webSocketController, &WebSocketController::chatResponseReceived,
        this, &MainController::onWebSocketChatResponse);
    connect(m_webSocketController, &WebSocketController::presenceReceived,
        this, &MainController::onWebSocketPresence);
    connect(m_webSocketController, &WebSocketController::errorOccurred,
        this, &MainController::onWebSocketError);
    connect(m_webSocketController, &WebSocketController::connectionStateChanged,
        this, &MainController::onWebSocketStateChanged);
    connect(m_webSocketController, &WebSocketController::computerUseActionReceived,
        this, &MainController::onComputerUseAction);
    connect(m_webSocketController, &WebSocketController::computerUseDoneReceived,
        this, &MainController::onComputerUseDone);

    m_computerUseExecutor = new ComputerUseExecutor(this);
    connect(m_computerUseExecutor, &ComputerUseExecutor::observationReady,
        this, &MainController::onComputerUseObservation);

    if (m_mainWidget) {
        QtSpineManager* spine = m_mainWidget->spineManager();
        if (spine) {
            connect(spine, &QtSpineManager::patEnded, this, &MainController::onPatEnded);
        }
    }

    FINE_DEBUG_OUTPUT("[Startup] TTS warmup queued; WebSocket connect deferred until splash hooks are ready");

    if (m_userInputWidget) {
        connect(m_userInputWidget, &UserInputWidget::textSubmitted,
            this, &MainController::processInputText);
    }

}

MainController::~MainController()
{

}

void MainController::startSession()
{
    m_webSocketController->connectToServer();
    FINE_DEBUG_OUTPUT("[WebSocket] Connecting to: " + GET_STRING_FROM_JSON(_global_config, "aronalm", "websocket_url"));
}

void MainController::executeOutput(const QString& text)
{
    ttsRequestParams.emotion = m_currentEmotion;
    const AronaTtsRef::TtsRef ref = m_ttsRefMap.resolve(m_currentEmotion);
    ttsRequestParams.refAudioPath = ref.refAudioPath;
    ttsRequestParams.promptText = ref.promptText;
    const QStringList parts = SpokenTextSplitter::split(text);
    for (const QString& part : parts) {
        ttsRequestParams.text = part;
        m_ttsManager->requestTTSPost(ttsRequestParams);
    }
}

void MainController::onTTSFinished(const QByteArray& audioData, const QString& mediaType, const QString& text, const QString& emotion)
{
    holdOrPresentOutput(audioData, mediaType, false, text, emotion, false);
}

void MainController::onTTSStreamReady(const QString& text, const QString& emotion)
{
    holdOrPresentOutput(QByteArray(), QString(), false, text, emotion, true);
}

void MainController::onTtsPlaybackEnded()
{
    if (!m_streamingPresentation) {
        return;
    }
    m_streamingPresentation = false;
    m_mainWidget->hideOutputText();
    m_mainWidget->clearAnimation(2, 0.2f);
    restorePresenceFace();
    m_audioRecorder->setPlaybackGuard(false);
}

void MainController::presentOutput(const QByteArray& audioData, const QString& mediaType, const QString& text, const QString& emotion, bool isStream)
{
    Q_UNUSED(mediaType);
    const QString line = text;
    const QString face = emotion.isEmpty() ? QStringLiteral("normal") : emotion;
    m_currentText = line;
    m_currentEmotion = face;
    ++m_outputGeneration;
    const int gen = m_outputGeneration;
    m_streamingPresentation = isStream;

    m_audioRecorder->setPlaybackGuard(true);
    m_bargeInGuardTimer.start();
    m_mainWidget->showOutputText(line);
    if (m_measuringUserTurn) {
        FINE_DEBUG_OUTPUT(QString("[Latency] User send to text on screen: %1 ms")
            .arg(m_userTurnTimer.elapsed()));
        m_measuringUserTurn = false;
    }
    const QString expressionAnim = AronaEmotion::toAnimationName(face);
    m_mainWidget->setAnimation(expressionAnim, 1, true);
    m_mainWidget->setAnimation("Arona_Work_In_1_CN", 2, true);

    if (isStream) {
        m_ttsManager->startStreamPlayback();
        return;
    }

    const double wavSec = m_ttsManager->playAudio(audioData);
    int duration = qMax(500, line.size() * 100);
    if (wavSec > 0) {
        duration = static_cast<int>(1000 * wavSec);
    }
    QTimer::singleShot(duration, this, [this, gen]() {
        if (gen != m_outputGeneration) {
            return;
        }
        m_mainWidget->hideOutputText();
        m_mainWidget->clearAnimation(2, 0.2f);
        restorePresenceFace();
        m_audioRecorder->setPlaybackGuard(false);
    });
}

void MainController::onTTSError(const QString& errorString, const QString& text, const QString& emotion)
{
    ERROR_DEBUG_OUTPUT("[TTS Operation]TTS error: " + errorString);

    if (text.isEmpty()) {
        m_measuringUserTurn = false;
        if (m_awaitingStartupWelcome) {
            m_awaitingStartupWelcome = false;
            if (m_splashActive) {
                emit welcomePlaybackReady();
            }
        }
        m_ttsManager->notifyPlaybackFinished();
        return;
    }

    holdOrPresentOutput(QByteArray(), QString(), true, text, emotion, false);
}

void MainController::presentOutputError(const QString& text, const QString& emotion)
{
    const QString line = text;
    const QString face = emotion.isEmpty() ? QStringLiteral("normal") : emotion;
    m_currentText = line;
    m_currentEmotion = face;
    ++m_outputGeneration;
    const int gen = m_outputGeneration;
    m_streamingPresentation = false;

    m_mainWidget->showOutputText(line);
    if (m_measuringUserTurn) {
        FINE_DEBUG_OUTPUT(QString("[Latency] User send to text on screen: %1 ms")
            .arg(m_userTurnTimer.elapsed()));
        m_measuringUserTurn = false;
    }
    const QString expressionAnim = AronaEmotion::toAnimationName(face);
    m_mainWidget->setAnimation(expressionAnim, 1, true);
    int duration = qMax(1500, line.size() * 100);
    QTimer::singleShot(duration, this, [this, gen]() {
        if (gen != m_outputGeneration) {
            return;
        }
        m_mainWidget->hideOutputText();
        restorePresenceFace();
        });
    m_ttsManager->notifyPlaybackFinished();
}

void MainController::holdOrPresentOutput(const QByteArray& audioData, const QString& mediaType, bool isError, const QString& text, const QString& emotion, bool isStream)
{
    if (m_awaitingStartupWelcome) {
        m_awaitingStartupWelcome = false;
        if (m_splashActive) {
            m_hasPendingOutput = true;
            m_pendingIsError = isError;
            m_pendingIsStream = isStream;
            m_pendingAudio = audioData;
            m_pendingMediaType = mediaType;
            m_pendingText = text;
            m_pendingEmotion = emotion;
            FINE_DEBUG_OUTPUT(QString("[Main Controller] Welcome TTS %1, waiting for splash close")
                .arg(isError ? "error" : "ready"));
            emit welcomePlaybackReady();
            if (receivers(SIGNAL(welcomePlaybackReady())) == 0) {
                FINE_DEBUG_OUTPUT("[Main Controller] Splash already gone, presenting welcome now");
                onSplashClosed();
            }
            return;
        }
    }

    if (isError) {
        presentOutputError(text, emotion);
    } else {
        presentOutput(audioData, mediaType, text, emotion, isStream);
    }
}

void MainController::onSplashClosed()
{
    if (!m_splashActive) {
        return;
    }
    m_splashActive = false;
    FINE_DEBUG_OUTPUT("[Main Controller] Splash closed");
    if (!m_hasPendingOutput) {
        return;
    }
    m_hasPendingOutput = false;
    if (m_pendingIsError) {
        presentOutputError(m_pendingText, m_pendingEmotion);
    } else {
        presentOutput(m_pendingAudio, m_pendingMediaType, m_pendingText, m_pendingEmotion, m_pendingIsStream);
    }
    m_pendingAudio.clear();
    m_pendingMediaType.clear();
    m_pendingText.clear();
    m_pendingEmotion.clear();
    m_pendingIsStream = false;
}

void MainController::dismissSplashOnUnrecoverableError()
{
    if (!m_splashActive) {
        return;
    }
    m_awaitingStartupWelcome = false;
    FINE_DEBUG_OUTPUT("[Main Controller] Unrecoverable WS error, dismissing splash");
    emit welcomePlaybackReady();
}

void MainController::startAudioProcessing()
{
    if (m_listening) {
        return;
    }
    if (!m_tencentRecognizer->isInitialized()) {
        ERROR_DEBUG_OUTPUT("[Audio Input Processing]Realtime ASR is not initialized");
        return;
    }
    if (!m_audioRecorder->startRecording()) {
        ERROR_DEBUG_OUTPUT("[Audio Input Processing]Failed to start recording");
        return;
    }
    if (!m_tencentRecognizer->startRealtime()) {
        m_audioRecorder->stopRecording();
        ERROR_DEBUG_OUTPUT("[Audio Input Processing]Failed to start realtime ASR");
        return;
    }
    m_listening = true;
    m_transcriptSeq = 0;
    m_latestTranscript.clear();
    m_lastSentTranscript.clear();
    m_webSocketController->sendListenState(true);
    FINE_DEBUG_OUTPUT("[Audio Input Processing]Continuous listen on");
}

bool MainController::isListening() const
{
    return m_listening;
}

void MainController::stopAudioProcessing()
{
    if (!m_listening) {
        m_audioRecorder->stopRecording();
        m_tencentRecognizer->stopRealtime();
        return;
    }
    flushPendingTranscript();
    m_webSocketController->sendListenState(false);
    m_listening = false;
    m_latestTranscript.clear();
    m_lastSentTranscript.clear();
    m_audioRecorder->stopRecording();
    m_audioRecorder->setPlaybackGuard(false);
    m_tencentRecognizer->stopRealtime();
    FINE_DEBUG_OUTPUT("[Audio Input Processing]Continuous listen off");
}

void MainController::toggleMouseTransparent()
{
    bool nextState = !m_mainWidget->isMouseTransparent();
    m_mainWidget->setMouseTransparent(nextState);
    FINE_DEBUG_OUTPUT(QString("[Main Controller] Mouse transparent toggled to: %1")
        .arg(nextState ? "true" : "false"));
}

void MainController::showUserInput()
{
    if (!m_userInputWidget) {
        ERROR_DEBUG_OUTPUT("[Main Controller] UserInputWidget is null");
        return;
    }
    m_userInputWidget->showForInput();
    FINE_DEBUG_OUTPUT("[Main Controller] User input widget shown");
}

bool MainController::isImageInputEnabled() const
{
    return GET_BOOL_FROM_JSON(_global_config, "settings", "image_input");
}

void MainController::toggleImageInput()
{
    setImageInputEnabled(!isImageInputEnabled());
}

void MainController::setImageInputEnabled(bool enabled)
{
    if (isImageInputEnabled() == enabled) {
        emit imageInputChanged(enabled);
        return;
    }
    SET_BOOL_TO_JSON(_global_config, "settings", "image_input", enabled);
    if (_global_config && !_global_config->save()) {
        ERROR_DEBUG_OUTPUT("[Main Controller] Failed to persist image_input to config.json");
    }
    FINE_DEBUG_OUTPUT(QString("[Main Controller] Image input toggled to: %1")
        .arg(enabled ? "true" : "false"));
    emit imageInputChanged(enabled);
}

QString MainController::maybeCaptureScreenBase64() const
{
    if (!isImageInputEnabled()) {
        return {};
    }
    QList<QWidget*> exclude;
    if (m_mainWidget) {
        exclude << m_mainWidget;
    }
    if (m_userInputWidget && m_userInputWidget->isVisible()) {
        exclude << m_userInputWidget;
    }
    const bool compress = GET_BOOL_FROM_JSON(_global_config, "settings", "compress_screenshot");
    const QString imageBase64 = ScreenCapture::grabJpegBase64(exclude, compress);
    if (imageBase64.isEmpty()) {
        ERROR_DEBUG_OUTPUT("[Main Controller] Screenshot failed, send text only");
    }
    return imageBase64;
}

QList<QWidget*> MainController::computerUseExcludeWindows() const
{
    QList<QWidget*> exclude;
    if (m_mainWidget) {
        exclude << m_mainWidget;
    }
    if (m_userInputWidget && m_userInputWidget->isVisible()) {
        exclude << m_userInputWidget;
    }
    return exclude;
}

void MainController::sendComputerUseDisabled(const QJsonObject& action)
{
    QJsonObject observation;
    observation.insert(QStringLiteral("run_id"), action.value(QStringLiteral("run_id")).toString());
    observation.insert(QStringLiteral("step"), action.value(QStringLiteral("step")).toInt());
    observation.insert(QStringLiteral("ok"), false);
    observation.insert(QStringLiteral("error"), QStringLiteral("disabled"));
    if (m_webSocketController) {
        m_webSocketController->sendComputerUseObservation(observation);
    }
}

void MainController::onComputerUseAction(const QJsonObject& action)
{
    if (m_computerUseStopRequested) {
        FINE_DEBUG_OUTPUT("[Computer Use] Action dropped: stop requested");
        return;
    }
    if (!GET_BOOL_FROM_JSON(_global_config, "computer_use", "enabled")) {
        FINE_DEBUG_OUTPUT("[Computer Use] Action ignored: client disabled");
        sendComputerUseDisabled(action);
        return;
    }
    if (!m_computerUseExecutor) {
        sendComputerUseDisabled(action);
        return;
    }
    m_computerUseActive = true;
    m_computerUseExecutor->setExcludeWindows(computerUseExcludeWindows());
    m_computerUseExecutor->execute(action);
}

void MainController::onComputerUseObservation(const QJsonObject& observation)
{
    if (!m_webSocketController || !m_webSocketController->isConnected()) {
        ERROR_DEBUG_OUTPUT("[Computer Use] Drop observation: not connected");
        return;
    }
    m_webSocketController->sendComputerUseObservation(observation);
}

void MainController::onComputerUseDone(const QJsonObject& message)
{
    m_computerUseStopRequested = false;
    m_computerUseActive = false;
    FINE_DEBUG_OUTPUT(QString("[Computer Use] Done run=%1 ok=%2 summary=%3")
        .arg(message.value(QStringLiteral("run_id")).toString())
        .arg(message.value(QStringLiteral("ok")).toBool() ? "true" : "false")
        .arg(message.value(QStringLiteral("summary")).toString()));
}

void MainController::onAudioError(const QString& error)
{
    ERROR_DEBUG_OUTPUT("[Audio Input Processing]Audio error!");
}

void MainController::onPcmFrame(const QByteArray& frame)
{
    if (!m_listening) {
        return;
    }
    m_tencentRecognizer->sendAudio(frame);
}

void MainController::onSpeechDetected()
{
    if (!m_listening) {
        return;
    }
    if (m_bargeInGuardTimer.isValid() && m_bargeInGuardTimer.elapsed() < 400) {
        return;
    }
    if (m_ttsManager->isPlayingAudio() || m_waitingForAIResponse || m_hasPendingOutput) {
        FINE_DEBUG_OUTPUT("[Audio Input Processing]Barge-in speech detected");
        interruptOutput();
        return;
    }
    if (m_webSocketController->isConnected()) {
        m_webSocketController->sendInterrupt();
    }
}

void MainController::cancelComputerUse()
{
    FINE_DEBUG_OUTPUT("[Computer Use] Cancel requested");
    if (m_computerUseActive
        || m_waitingForAIResponse
        || (m_computerUseExecutor && m_computerUseExecutor->isBusy())) {
        m_computerUseStopRequested = true;
    }
    interruptOutput();
}

void MainController::interruptOutput()
{
    FINE_DEBUG_OUTPUT("[Main Controller] Interrupting output");
    ++m_outputGeneration;
    m_streamingPresentation = false;
    m_ttsManager->interruptPlayback();
    m_audioRecorder->setPlaybackGuard(false);
    m_waitingForAIResponse = false;
    m_measuringUserTurn = false;
    m_mainWidget->hideOutputText();
    m_mainWidget->clearAnimation(2, 0.2f);
    restorePresenceFace();
    if (m_computerUseActive || (m_computerUseExecutor && m_computerUseExecutor->isBusy())) {
        m_computerUseStopRequested = true;
    }
    if (m_computerUseExecutor) {
        m_computerUseExecutor->cancel();
    }
    if (m_webSocketController->isConnected()) {
        m_webSocketController->sendInterrupt();
    }
}

void MainController::onRecognizeError(const QString& error)
{
    ERROR_DEBUG_OUTPUT("[Audio Input Processing]Recognize error: " + error);
}

void MainController::sendTranscriptToBackend(const QString& text)
{
    if (text.contains(QStringLiteral("[Tencent Speech Recognizer]"))
        || text.contains(QStringLiteral("Didnt recognize"), Qt::CaseInsensitive)
        || text.contains(QStringLiteral("Didn't recognize"), Qt::CaseInsensitive)) {
        ERROR_DEBUG_OUTPUT("[Audio Input Processing]Ignoring unusable ASR text");
        return;
    }
    if (!m_webSocketController->isConnected()) {
        ERROR_DEBUG_OUTPUT("[Main Controller] WebSocket not connected, drop transcript");
        return;
    }
    ++m_transcriptSeq;
    m_webSocketController->sendTranscript(
        text,
        QString::number(m_transcriptSeq),
        0,
        maybeCaptureScreenBase64());
    m_lastSentTranscript = text;
}

void MainController::flushPendingTranscript()
{
    const QString trimmed = m_latestTranscript.trimmed();
    if (trimmed.isEmpty() || trimmed == m_lastSentTranscript) {
        return;
    }
    FINE_DEBUG_OUTPUT("[Audio Input Processing]Flush pending transcript on listen stop: " + trimmed);
    sendTranscriptToBackend(trimmed);
}

void MainController::onTranscriptReceived(const QString& text, bool isFinal, int sliceType)
{
    const QString trimmed = text.trimmed();
    FINE_DEBUG_OUTPUT(QString("[Audio Input Processing]ASR slice=%1 final=%2 text=%3")
        .arg(sliceType)
        .arg(isFinal ? "true" : "false")
        .arg(trimmed));
    if (!trimmed.isEmpty()) {
        m_latestTranscript = trimmed;
    }
    if (!m_listening || !isFinal || trimmed.isEmpty()) {
        return;
    }
    sendTranscriptToBackend(trimmed);
}

void MainController::processInputText(const QString& text)
{
    const QString trimmed = text.trimmed();
    FINE_DEBUG_OUTPUT("[Main Controller] Processing input: " + trimmed);

    if (trimmed.isEmpty()) {
        ERROR_DEBUG_OUTPUT("[Main Controller] Empty input, skip send");
        return;
    }

    // 检查 WebSocket 是否已连接
    if (!m_webSocketController->isConnected()) {
        // 如果未连接，给出本地提示
        executeOutput("AI服务未连接，请检查网络后重试");
        ERROR_DEBUG_OUTPUT("[Main Controller] WebSocket not connected, cannot process input");
        return;
    }

    // 文字防重入（不是「阿洛娜在等这轮答完」）；听写路径不加这把锁
    if (m_waitingForAIResponse) {
        FINE_DEBUG_OUTPUT("正在处理上一条消息，请稍候");
        FINE_DEBUG_OUTPUT("[Main Controller] Text send re-entry blocked");
        return;
    }

    m_waitingForAIResponse = true;
    m_computerUseStopRequested = false;

    // 给用户一个等待提示
    FINE_DEBUG_OUTPUT("[Main Controller] Generating responce...");

    // 发送消息给AI服务端
    // 可以从配置中读取是否使用 RAG、记忆等功能
    bool useRag = GET_BOOL_FROM_JSON(_global_config, "aronalm", "use_rag");
    bool useMemory = GET_BOOL_FROM_JSON(_global_config, "aronalm", "use_memory");

    m_backendTimer.restart();
    m_userTurnTimer.restart();
    m_measuringUserTurn = true;

    m_webSocketController->sendChatMessage(trimmed, useRag, useMemory, maybeCaptureScreenBase64());

    FINE_DEBUG_OUTPUT("[Main Controller] Sent to AI service: " + trimmed.left(50) + "...");
}

void MainController::onWebSocketConnected(const QString& sessionId)
{
    FINE_DEBUG_OUTPUT("[WebSocket] Connected! Session ID: " + sessionId);
    FINE_DEBUG_OUTPUT(QString("[Startup] WebSocket connected, TTS models reloaded: %1/2")
        .arg(m_ttsModelsLoaded));
}

void MainController::onWebSocketChatResponse(const QString& content, const QString& contextUsed, double latency, const QString& emotion)
{
    FINE_DEBUG_OUTPUT(QString("[Latency] Backend RTT: %1 ms (server_reported: %2s)")
        .arg(m_backendTimer.elapsed())
        .arg(latency, 0, 'f', 2));
    FINE_DEBUG_OUTPUT("[WebSocket] Received AI response: " + content.left(50) + "...");
    FINE_DEBUG_OUTPUT(QString("[WebSocket] Context: %1, Latency: %2s, Emotion: %3")
        .arg(contextUsed)
        .arg(latency)
        .arg(emotion));
    if (m_awaitingStartupWelcome && contextUsed.contains(QStringLiteral("welcome"))) {
        FINE_DEBUG_OUTPUT("[WebSocket] Startup welcome chat_response received");
    }

    // 解除文字防重入（空 chat_response 也会走这里）
    m_waitingForAIResponse = false;
    m_measuringUserTurn = false;

    if (content.trimmed().isEmpty()) {
        FINE_DEBUG_OUTPUT(QString("[WebSocket] Silent skip (no speech), context=%1")
            .arg(contextUsed));
        if (contextUsed.contains(QStringLiteral("interact"))) {
            applySilentEmotion(emotion);
        }
        return;
    }

    m_currentEmotion = emotion.isEmpty() ? QStringLiteral("normal") : emotion;

    // 通过TTS播放AI回复
    executeOutput(content);
}

void MainController::onPatEnded(int durationMs)
{
    if (durationMs < kPatMinDurationMs) {
        FINE_DEBUG_OUTPUT(QString("[Interact] Pat skipped durationMs=%1 min=%2")
            .arg(durationMs)
            .arg(kPatMinDurationMs));
        return;
    }
    if (m_patInteractCooldown.isValid() && m_patInteractCooldown.elapsed() < kPatCooldownMs) {
        FINE_DEBUG_OUTPUT(QString("[Interact] Pat skipped cooldown remaining=%1ms")
            .arg(kPatCooldownMs - static_cast<int>(m_patInteractCooldown.elapsed())));
        return;
    }
    if (!m_webSocketController || !m_webSocketController->isConnected()) {
        FINE_DEBUG_OUTPUT("[Interact] Pat skipped reason=not_connected");
        return;
    }
    m_patInteractCooldown.restart();
    m_webSocketController->sendInteract(QStringLiteral("pat_head"), durationMs);
    FINE_DEBUG_OUTPUT(QString("[Interact] Sent pat_head durationMs=%1").arg(durationMs));
}

void MainController::onWebSocketPresence(const QString& emotion)
{
    const QString face = emotion.isEmpty() ? QStringLiteral("normal") : emotion;
    m_presenceEmotion = face;
    FINE_DEBUG_OUTPUT(QString("[Presence] emotion=%1 presenting=%2")
        .arg(face)
        .arg(isOutputPresenting() ? QStringLiteral("yes") : QStringLiteral("no")));
    if (isOutputPresenting()) {
        return;
    }
    applyPresenceFace(face);
}

void MainController::applyPresenceFace(const QString& emotion)
{
    if (!m_mainWidget) {
        return;
    }
    const QString face = emotion.isEmpty() ? QStringLiteral("normal") : emotion;
    const QString expressionAnim = AronaEmotion::toAnimationName(face);
    m_mainWidget->setAnimation(expressionAnim, 1, true);
}

void MainController::restorePresenceFace()
{
    applyPresenceFace(m_presenceEmotion);
}

bool MainController::isOutputPresenting() const
{
    if (m_streamingPresentation || m_hasPendingOutput) {
        return true;
    }
    return m_ttsManager && m_ttsManager->isPlayingAudio();
}

void MainController::applySilentEmotion(const QString& emotion)
{
    const QString face = emotion.isEmpty() ? QStringLiteral("normal") : emotion;
    m_currentEmotion = face;
    ++m_outputGeneration;
    const int gen = m_outputGeneration;
    applyPresenceFace(face);
    QTimer::singleShot(kSilentInteractEmotionMs, this, [this, gen]() {
        if (gen != m_outputGeneration) {
            return;
        }
        restorePresenceFace();
    });
}

void MainController::onWebSocketError(WebSocketController::ErrorCode code, const QString& message)
{
    ERROR_DEBUG_OUTPUT(QString("[WebSocket] Error (code: %1): %2").arg(static_cast<int>(code)).arg(message));

    if (m_waitingForAIResponse) {
        FINE_DEBUG_OUTPUT(QString("[Latency] Backend RTT (failed): %1 ms")
            .arg(m_backendTimer.elapsed()));
        m_measuringUserTurn = false;
    }

    // 解除文字防重入
    m_waitingForAIResponse = false;

    // 根据错误类型给出不同的用户提示
    QString userMessage;
    switch (code) {
    case WebSocketController::ErrorCode::ConnectionRefused:
        userMessage = "无法连接到AI服务，请检查服务是否启动";
        break;
    case WebSocketController::ErrorCode::ConnectionTimeout:
        userMessage = "连接AI服务超时，请检查网络";
        break;
    case WebSocketController::ErrorCode::HeartbeatTimeout:
        userMessage = "与AI服务连接中断，正在尝试重连";
        break;
    case WebSocketController::ErrorCode::ReconnectFailed:
        userMessage = "无法重新连接到AI服务";
        break;
    case WebSocketController::ErrorCode::NetworkError:
        userMessage = "无法连接到AI服务，请检查服务是否启动";
        break;
    default:
        userMessage = "AI服务出现错误: " + message;
        break;
    }

    if (m_splashActive) {
        m_currentText = userMessage;
        m_currentEmotion = QStringLiteral("normal");
        m_hasPendingOutput = true;
        m_pendingIsError = true;
        dismissSplashOnUnrecoverableError();
        return;
    }

    // 显示文字
    m_mainWidget->showOutputText(userMessage);
    // 计算播放时长
    int duration = userMessage.size() * 100; // 每个字符100ms
    // 在duration之后清除显示的文字，停止动画
    QTimer::singleShot(duration, this, [this]() {
        m_mainWidget->hideOutputText();
        });
}

void MainController::onWebSocketStateChanged(WebSocketController::ConnectionState state)
{
    QString stateStr;
    switch (state) {
    case WebSocketController::ConnectionState::Disconnected:
        stateStr = "Disconnected";
        break;
    case WebSocketController::ConnectionState::Connecting:
        stateStr = "Connecting";
        break;
    case WebSocketController::ConnectionState::Connected:
        stateStr = "Connected";
        break;
    case WebSocketController::ConnectionState::Reconnecting:
        stateStr = "Reconnecting";
        break;
    }
    FINE_DEBUG_OUTPUT("[WebSocket] State changed: " + stateStr);

    // 如果连接断开，更新UI状态
    if (state == WebSocketController::ConnectionState::Disconnected) {
        if (m_waitingForAIResponse) {
            FINE_DEBUG_OUTPUT(QString("[Latency] Backend RTT (failed): %1 ms")
                .arg(m_backendTimer.elapsed()));
            m_measuringUserTurn = false;
        }
        m_waitingForAIResponse = false;
    }
}
