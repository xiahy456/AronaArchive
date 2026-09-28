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

#ifndef TTSMANAGER_H
#define TTSMANAGER_H

#include "Defines.h"
#include "JsonOperation.h"
#include "GlobalVariables.h"

#include <QObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QUrl>
#include <QUrlQuery>
#include <QJsonObject>
#include <QJsonDocument>
#include <QFile>
#include <QAudioOutput>
#include <QBuffer>
#include <QAudioFormat>
#include <QJsonArray>
#include <QMediaDevices>
#include <QAudioSink>
#include <QQueue>
#include <QElapsedTimer>
#include <QSharedPointer>
#include <QIODevice>

class TTSManager : public QObject
{
    Q_OBJECT

public:
    explicit TTSManager(QObject* parent = nullptr);
    ~TTSManager();

    // 设置服务器地址
    void setServerAddress(const QString& host, int port);

    bool isMinimalBackend() const;
    bool isStreaming() const;

    // TTS请求参数结构体
    struct TTSRequestParams {
        QString text = "";  // 要合成的文本
        QString textLang = "zh";    // 文本语言
        QString refAudioPath = "";  // 参考音频路径
        QStringList auxRefAudioPaths;   // 辅助参考音频路径
        QString promptText = "";    // 提示文本
        QString promptLang = "zh";  // 提示文本语言
        int topK = 5;   // top k采样
        double topP = 1.0;  // top p采样
        double temperature = 1.0;   // 温度参数
        QString textSplitMethod = "cut0";   // 文本分割方法
        int batchSize = 1;  // 批处理大小
        double batchThreshold = 0.75;   // 批处理阈值
        bool splitBucket = true;    // 是否分割桶
        double speedFactor = 1.0;   // 语速因子
        double fragmentInterval = 0.3;  // 片段间隔
        int seed = -1;  // 随机种子
        bool parallelInfer = true;  // 并行推理
        double repetitionPenalty = 1.35;    // 重复惩罚
        int sampleSteps = 32;   // 采样步数
        bool superSampling = false; // 超采样
        QString mediaType = "wav";  // 媒体类型
        QString emotion = "normal";  // 本条表情（随请求传递，不读全局）
    };

    // 发送TTS请求（GET方式）
    void requestTTSGet(const TTSRequestParams& params);

    // 发送TTS请求（POST方式）
    void requestTTSPost(const TTSRequestParams& params);

    // 控制命令
    void sendControlCommand(const QString& command);

    // 设置GPT模型
    void setGPTWeights(const QString& weightsPath);

    // 设置Sovits模型
    void setSovitsWeights(const QString& weightsPath);

    // 预热参考音频与 prompt cache（不播、不上字幕）
    void warmup(const TTSRequestParams& params);

    // 播放音频；返回 WAV 时长（秒，失败为 -1）。上一条未结束时不要打断。
    double playAudio(const QByteArray& audioData);

    // 流式：播放当前已交付会话（首包已到）。时长未知时返回 -1。
    double startStreamPlayback();

    bool isPlayingAudio() const;
    void interruptPlayback();

    // 本条已呈现完毕（播完 / TTS 失败字幕 / 跳过播放），允许播放队列下一条
    void notifyPlaybackFinished();

    // 保存音频到文件
    bool saveAudioToFile(const QByteArray& audioData, const QString& filePath);

	// 获取音频长度（秒）
    double getWavDuration(const QByteArray& audioData);

signals:
    // TTS完成信号（带本条文本与表情，不要再用全局 m_currentText）
    void ttsFinished(const QByteArray& audioData, const QString& mediaType, const QString& text, const QString& emotion);
    // 流式：首包 PCM 到达且轮到该句播放
    void ttsStreamReady(const QString& text, const QString& emotion);
    // TTS错误信号
    void ttsError(const QString& errorString, const QString& text, const QString& emotion);
    // 命令执行完成信号
    void commandFinished(bool success, const QString& message);
    // 模型切换完成信号
    void modelSwitched(bool success, const QString& message);
    // 当前句音频实际播完（失败字幕路径不发）
    void playbackEnded();

private slots:
    void onNetworkReplyFinished();
    void onTtsReadyRead();

private:
    struct QueuedRequest {
        enum RequestType {
            TTSGet,
            TTSPost,
            WarmupTTS,
            ControlCommand,
            SetGPTWeights,
            SetSovitsWeights,
            SetReferAudio
        };

        RequestType type;
        TTSRequestParams params;  // 用于TTS请求
        QString command;          // 用于控制命令
        QString weightsPath;      // 用于模型切换 / 参考音频

        QueuedRequest(RequestType t, const TTSRequestParams& p)
            : type(t), params(p) {
        }
        QueuedRequest(RequestType t, const QString& cmd)
            : type(t), command(cmd) {
        }
        QueuedRequest(RequestType t, const QString& path, bool isModelWeight)
            : type(t), weightsPath(path) {
            Q_UNUSED(isModelWeight);
        }
    };

    struct StreamSession {
        QByteArray raw;
        QByteArray pcm;
        bool headerParsed = false;
        bool firstPcmSeen = false;
        bool complete = false;
        bool jsonError = false;
        bool enqueued = false;
        int sampleRate = 32000;
        int channelCount = 1;
        int bitsPerSample = 16;
        int pcmOffset = -1;
        QString text;
        QString emotion;
        QString mediaType;
    };

    struct ReadyPlayback {
        bool isError = false;
        bool isStream = false;
        QByteArray audioData;
        QString mediaType;
        QString text;
        QString emotion;
        QString errorString;
        QSharedPointer<StreamSession> stream;
    };

    struct WavPcmInfo {
        QByteArray pcm;
        int sampleRate = 32000;
        int channelCount = 1;
        int bitsPerSample = 16;
        double durationSec = -1;
    };

    struct WavHeaderInfo {
        int sampleRate = 0;
        int channelCount = 0;
        int bitsPerSample = 0;
        int pcmOffset = -1;
        quint32 pcmSize = 0;
    };

    QQueue<QueuedRequest> requestQueue;
    QQueue<ReadyPlayback> m_readyPlayback;

    QNetworkAccessManager* networkManager;
    QString serverHost;
    int serverPort;
    bool m_minimalBackend;
    bool m_streaming;
    QString m_voice;

    QNetworkReply* currentReply;
    QString currentMediaType;

    QAudioSink* audioSink;
    QBuffer* audioBuffer;
    QIODevice* m_streamPush;       // start() 推流设备，stop 后失效
    qint64 m_streamWritten;        // 已成功写入声卡的 PCM 字节

    bool isProcessingRequest;
    bool m_awaitingPlayback;
    bool m_playingAudio;
    bool m_ignoreAudioIdle;
    bool m_currentIsWarmup;
    bool m_restartingStream;
    bool m_streamFeedScheduled;
    bool m_streamEndScheduled;
    bool m_inStreamFeed;
    int m_playbackGeneration;
    QString currentTtsText;
    QString currentTtsEmotion;
    int requestTimeoutMs;  // HTTP 请求超时（毫秒），0 表示不限制
    QElapsedTimer m_ttsRequestTimer;  // TTS HTTP RTT
    QElapsedTimer m_streamPlayTimer;  // 流式开播墙钟，用于排空硬件缓冲
    QSharedPointer<StreamSession> m_currentReceive;
    QSharedPointer<StreamSession> m_deliveredStream;

    void processNextRequest();
    void executeTTSGet(const TTSRequestParams& params);
    void executeTTSPost(const TTSRequestParams& params);
    void executeControlCommand(const QString& command);
    void executeSetGPTWeights(const QString& weightsPath);
    void executeSetSovitsWeights(const QString& weightsPath);
    void executeSetReferAudio(const QString& audioPath);
    void cleanupCurrentReply();
    void applyRequestTimeout(QNetworkRequest& request) const;
    QUrl buildBaseUrl() const;
    QUrlQuery buildQueryFromParams(const TTSRequestParams& params) const;
    QJsonObject buildJsonFromParams(const TTSRequestParams& params) const;
    QJsonObject buildMinimalJsonFromParams(const TTSRequestParams& params) const;
    QString rewriteRefAudioPath(const QString& path) const;
    bool isTtsReplyPath(const QString& path) const;
    void enqueueTtsPlaybackFromReply(QNetworkReply* reply, bool httpError, const QString& errorString);
    void tryDeliverPlayback();
    bool extractWavPcm(const QByteArray& wav, WavPcmInfo* out) const;
    bool parseWavHeader(const QByteArray& wav, WavHeaderInfo* out) const;
    void beginStreamingReceive();
    void consumeReceiveBuffer();
    void enqueueStreamSession(const QSharedPointer<StreamSession>& session);
    void enqueueStreamError(const QSharedPointer<StreamSession>& session, const QString& errorString);
    void finishStreamingReceive(QNetworkReply* reply, bool httpError, const QString& errorString);
    void appendSessionPcm(const QSharedPointer<StreamSession>& session, const QByteArray& pcm);
    void feedStreamAudio();
    void restartStreamSink();
    void scheduleStreamFeed(int delayMs);
    void scheduleStreamPlaybackEnd();
    void finishAudioPlayback();
    void stopAudioSink();
    void attachStreamingReadyRead();
    double pcmDurationSec(qint64 bytes, int sampleRate, int channelCount, int bitsPerSample) const;

};

#endif // TTSMANAGER_H
