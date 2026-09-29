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


#pragma once

#include "Defines.h"
#include "GlobalVariables.h"

#include <QElapsedTimer>
#include <QFont>
#include <QImage>
#include <QStringList>
#include <QVector>
#include <QWidget>
#include "ui_StartWidget.h"

class QEventLoop;
class QMediaPlayer;
class QTimer;
class QVariantAnimation;
class QVideoFrame;
class QVideoSink;

class StartWidget : public QWidget
{
	Q_OBJECT

public:
	StartWidget(QWidget *parent = nullptr);
	~StartWidget();

	// 阻塞直到预解码+回放结束（内部跑事件循环）
	void waitUntilVideoEnded();
	// ESC 可能在 MainController 接线前就关掉遮罩
	bool hasClosed() const;

signals:
	void closeFinished();

public slots:
	void onSpineReady();
	void onAppReady();
	void onBackendConnected();
	void onBackendFailed();
	void onEscapePressed();

protected:
	void paintEvent(QPaintEvent* event) override;
	void showEvent(QShowEvent* event) override;

private:
	void onVideoFrame(const QVideoFrame& frame);
	void onDecodeFinished();
	void startCachedPlayback(qint64 durationMs);
	void onPlaybackTick();
	void markVideoEnded();
	void tryClose();
	void loadHoldImage();
	void switchToHoldImage();
	void startCloseScaleAnimation();
	void finishClose();
	void startStartupText();
	void onTypewriterTick();
	void startLoadingDots();
	void stopStartupText();
	bool shouldKeepFrame(const QVideoFrame& frame);
	int maxCacheFrames() const;
	QImage makeDisplayFrame(const QImage& source) const;
	static QRect sourceCropRect(const QSize& frameSize, const QSize& targetSize);

	Ui::StartWidgetClass ui;
	QMediaPlayer* m_player = nullptr;
	QVideoSink* m_videoSink = nullptr;
	QEventLoop* m_videoLoop = nullptr;
	QTimer* m_playbackTimer = nullptr;
	QTimer* m_typeTimer = nullptr;
	QVariantAnimation* m_closeAnim = nullptr;
	QVector<QImage> m_frames;
	QImage m_frame;
	QImage m_holdImage;
	QStringList m_startupLines;
	QStringList m_visibleLines;
	QFont m_startupFont;
	int m_frameIndex = 0;
	int m_startupFps = 30;
	int m_decodeIndex = 0;
	int m_typeLine = 0;
	int m_typeCol = 0;
	int m_dotsIndex = 0;
	qint64 m_nextKeepTimeUs = 0;
	qreal m_closeScaleY = 1.0;
	QElapsedTimer m_decodeTimer;
	QElapsedTimer m_playbackElapsed;
	bool m_preloading = true;
	bool m_loggedAlpha = false;
	bool m_videoEnded = false;
	bool m_spineReady = false;
	bool m_appReady = false;
	bool m_backendReady = false;
	bool m_backendFailed = false;
	bool m_introFinished = false;
	bool m_closing = false;
	bool m_closeFinishedEmitted = false;
	bool m_waitingLineGap = false;
	bool m_showingDots = false;
};
