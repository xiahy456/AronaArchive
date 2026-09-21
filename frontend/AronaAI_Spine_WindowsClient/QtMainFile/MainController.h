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

#include "Defines.h"
#include "GlobalVariables.h"

#include <QByteArray>
#include <QJsonObject>
#include <QList>
#include <QObject>
#include <QString>
#include <QMessageBox>
#include <QProcess>
#include <QElapsedTimer>

#include <MainWidget.h>
#include <TTSManager.h>
#include <AudioRecorder.h>
#include <TencentSpeechRecognizer.h>
#include "WebSocketController.h"
#include "UserInputWidget.h"
#include "AronaEmotionMap.h"
#include "AronaTtsRefMap.h"
#include "ComputerUseExecutor.h"

class MainController : public QObject
{
	Q_OBJECT

public:
	MainController(MainWidget* mainWidget, TTSManager* ttsManager, AudioRecorder* audioRecorder, TencentSpeechRecognizer* speechRecognizer, WebSocketController* webSocketController, UserInputWidget* userInputWidget);
	~MainController();

	// 执行输出（按 40 字拆句后排队 TTS；字幕按句上屏；合成可与上一条播放重叠）
	void executeOutput(const QString& text);
	// 开始持续聆听
	void startAudioProcessing();
	// 停止持续聆听
	void stopAudioProcessing();
	bool isListening() const;
	// 切换主界面鼠标穿透
	void toggleMouseTransparent();
	// 呼出用户文本输入界面
	void showUserInput();
	bool isImageInputEnabled() const;
	void toggleImageInput();
	void setImageInputEnabled(bool enabled);
	// 取消当前 computer use，并通知后端中断
	void cancelComputerUse();
	// 启动遮罩已关闭，冲刷待播欢迎语
	void onSplashClosed();
	// 遮罩信号接好后再连后端，避免连接失败早于槽绑定
	void startSession();

signals:
	void welcomePlaybackReady();
	void imageInputChanged(bool enabled);

private slots:
	// TTS工作完毕
	void onTTSFinished(const QByteArray& audioData, const QString& mediaType, const QString& text, const QString& emotion);
	// 流式：首包到达且轮到该句
	void onTTSStreamReady(const QString& text, const QString& emotion);
	// 流式：当前句音频实际播完
	void onTtsPlaybackEnded();
	// TTS失败（超时等）：仍显示字幕
	void onTTSError(const QString& errorString, const QString& text, const QString& emotion);
	// 音频输入出错
	void onAudioError(const QString& error);
	void onRecognizeError(const QString& error);
	void onTranscriptReceived(const QString& text, bool isFinal, int sliceType);
	void onSpeechDetected();
	void onPcmFrame(const QByteArray& frame);
	// WebSocket 相关槽函数
	void onWebSocketConnected(const QString& sessionId);
    void onWebSocketChatResponse(const QString& content, const QString& contextUsed, double latency, const QString& emotion);
    void onWebSocketPresence(const QString& emotion);
    void onWebSocketError(WebSocketController::ErrorCode code, const QString& message);
	void onWebSocketStateChanged(WebSocketController::ConnectionState state);
	void onPatEnded(int durationMs);
	void onComputerUseAction(const QJsonObject& action);
	void onComputerUseObservation(const QJsonObject& observation);
	void onComputerUseDone(const QJsonObject& message);

private:
	MainWidget* m_mainWidget;	// 主界面对象引用
	TTSManager* m_ttsManager;	// 语音合成管理器指针
	AudioRecorder* m_audioRecorder;	// 音频录制器对象
	TencentSpeechRecognizer* m_tencentRecognizer; // 腾讯的语音识别
	WebSocketController* m_webSocketController;	// 服务端websocket连接
	UserInputWidget* m_userInputWidget;	// 用户文本输入界面
	TTSManager::TTSRequestParams ttsRequestParams;	// 语音合成请求参数
	AronaTtsRef::Map m_ttsRefMap;	// emotion -> 参考音频 / prompt_text
	QString m_currentText = "";	// 当前正在处理的文本
	QString m_currentEmotion = "normal";	// 当前回复表情（英文值）
	QString m_presenceEmotion = "normal";	// 生命循环在场脸（英文值，独立于台词）
	bool m_waitingForAIResponse = false;	// 文字输入防重入，不是「阿洛娜在等这轮答完」；听写不加这把锁，靠空 chat_response 解锁
	bool m_listening = false;	// 持续聆听是否开启
	int m_transcriptSeq = 0;
	QString m_latestTranscript;	// 最近一次 ASR 文本（含未结束的 partial）
	QString m_lastSentTranscript;	// 已发给后端的最后一句
	QElapsedTimer m_bargeInGuardTimer;
	bool m_measuringUserTurn = false;	// 是否正在测量用户回合端到端耗时
	QElapsedTimer m_backendTimer;	// 后端 WebSocket RTT
	QElapsedTimer m_userTurnTimer;	// 用户发送到字幕上屏
	bool m_splashActive = true;	// 启动遮罩是否仍在
	bool m_awaitingStartupWelcome = true;	// 是否仍在等待启动欢迎语
	bool m_hasPendingOutput = false;	// 是否有待遮罩关闭后呈现的输出
	bool m_pendingIsError = false;	// 待呈现输出是否为 TTS 失败兜底
	bool m_pendingIsStream = false;	// 待呈现输出是否为流式首包
	bool m_streamingPresentation = false;	// 当前字幕是否随流式播完隐藏
	QByteArray m_pendingAudio;	// 待播放的欢迎语音频
	QString m_pendingMediaType;	// 待播放音频的媒体类型
	QString m_pendingText;	// 待呈现的本条文本
	QString m_pendingEmotion;	// 待呈现的本条表情
	int m_outputGeneration = 0;	// 字幕/口型定时器世代，避免上一条清掉下一条
	int m_ttsModelsLoaded = 0;	// 已切完的 TTS 权重数
	QElapsedTimer m_ttsWeightTimer;	// TTS 切权重耗时
	QElapsedTimer m_patInteractCooldown;	// 摸头 interact 冷却（从成功发送起算）
	ComputerUseExecutor* m_computerUseExecutor = nullptr;
	bool m_computerUseStopRequested = false;	// 用户已请求停止当前 computer use
	bool m_computerUseActive = false;	// 已收到 action、尚未收到 done

	// 处理用户输入的文本（语音识别或文本输入）
	void processInputText(const QString& text);
	void sendTranscriptToBackend(const QString& text);
	void flushPendingTranscript();
	QString maybeCaptureScreenBase64() const;
	QList<QWidget*> computerUseExcludeWindows() const;
	void sendComputerUseDisabled(const QJsonObject& action);
	void interruptOutput();
	void presentOutput(const QByteArray& audioData, const QString& mediaType, const QString& text, const QString& emotion, bool isStream = false);
	void presentOutputError(const QString& text, const QString& emotion);
	void holdOrPresentOutput(const QByteArray& audioData, const QString& mediaType, bool isError, const QString& text, const QString& emotion, bool isStream = false);
	void applySilentEmotion(const QString& emotion);
	void applyPresenceFace(const QString& emotion);
	void restorePresenceFace();
	bool isOutputPresenting() const;
	void dismissSplashOnUnrecoverableError();

};
