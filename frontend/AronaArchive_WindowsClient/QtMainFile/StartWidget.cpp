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


#include "StartWidget.h"

#include <BlueakaFontLoader.h>

#include <QApplication>
#include <QAudioOutput>
#include <QEasingCurve>
#include <QEventLoop>
#include <QFileInfo>
#include <QFontMetrics>
#include <QKeySequence>
#include <QMediaPlayer>
#include <QPainter>
#include <QPaintEvent>
#include <QScreen>
#include <QShortcut>
#include <QShowEvent>
#include <QTimer>
#include <QUrl>
#include <QVariantAnimation>
#include <QVideoFrame>
#include <QVideoSink>

StartWidget::StartWidget(QWidget *parent)
	: QWidget(parent)
{
	ui.setupUi(this);

	setWindowFlags(Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint | Qt::Tool);
	setAttribute(Qt::WA_TranslucentBackground);
	setAttribute(Qt::WA_NoSystemBackground);
	setAutoFillBackground(false);
	setFocusPolicy(Qt::StrongFocus);

	auto* escShortcut = new QShortcut(QKeySequence(Qt::Key_Escape), this);
	escShortcut->setContext(Qt::ApplicationShortcut);
	connect(escShortcut, &QShortcut::activated, this, &StartWidget::onEscapePressed);

	if (QScreen* screen = QApplication::primaryScreen()) {
		setGeometry(screen->geometry());
	}

	m_startupFont = BlueakaFontLoader::instance()->createFont(15 * WIDGET_ZOOM);

	loadHoldImage();

	m_startupFps = GET_INT_FROM_JSON(_global_config, "settings", "start_up_video_fps");
	if (m_startupFps <= 0) {
		m_startupFps = 30;
	}
	FINE_DEBUG_OUTPUT(QString("[StartWidget] startupFps=%1").arg(m_startupFps));

	m_playbackTimer = new QTimer(this);
	m_playbackTimer->setTimerType(Qt::PreciseTimer);
	connect(m_playbackTimer, &QTimer::timeout, this, &StartWidget::onPlaybackTick);

	m_typeTimer = new QTimer(this);
	m_typeTimer->setTimerType(Qt::PreciseTimer);
	connect(m_typeTimer, &QTimer::timeout, this, &StartWidget::onTypewriterTick);

	m_player = new QMediaPlayer(this);
	m_videoSink = new QVideoSink(this);
	auto* audioOutput = new QAudioOutput(this);
	audioOutput->setVolume(0.0); // 预解码阶段静音；短启动片无声也可
	m_player->setAudioOutput(audioOutput);
	m_player->setVideoSink(m_videoSink);

	connect(m_videoSink, &QVideoSink::videoFrameChanged, this, &StartWidget::onVideoFrame);

	connect(m_player, &QMediaPlayer::mediaStatusChanged, this, [this](QMediaPlayer::MediaStatus status) {
		FINE_DEBUG_OUTPUT(QString("[StartWidget] mediaStatus=%1 durationMs=%2 frames=%3")
			.arg(static_cast<int>(status))
			.arg(m_player->duration())
			.arg(m_frames.size()));
		if (status == QMediaPlayer::EndOfMedia && m_preloading) {
			onDecodeFinished();
		}
	});
	connect(m_player, &QMediaPlayer::errorOccurred, this, [this](QMediaPlayer::Error error, const QString& errorString) {
		ERROR_DEBUG_OUTPUT(QString("[StartWidget] play error=%1: %2")
			.arg(static_cast<int>(error))
			.arg(errorString));
		if (m_preloading) {
			onDecodeFinished();
		}
	});

	const QString configuredPath = GET_STRING_FROM_JSON(_global_config, "settings", "start_up_video_path");
	const QFileInfo videoInfo(configuredPath);
	const QString absolutePath = videoInfo.absoluteFilePath();
	FINE_DEBUG_OUTPUT(QString("[StartWidget] video path config='%1' absolute='%2' exists=%3")
		.arg(configuredPath)
		.arg(absolutePath)
		.arg(videoInfo.exists() ? "true" : "false"));

	if (configuredPath.isEmpty() || !videoInfo.exists()) {
		ERROR_DEBUG_OUTPUT("[StartWidget] startup video missing");
		m_preloading = false;
		switchToHoldImage();
		m_videoEnded = true;
	} else {
		m_preloading = true;
		m_decodeTimer.start();
		m_player->setSource(QUrl::fromLocalFile(absolutePath));
		m_player->play();
	}

	FINE_DEBUG_OUTPUT(QString("[StartWidget] shown geometry=%1x%2+%3+%4")
		.arg(width()).arg(height()).arg(x()).arg(y()));
}

StartWidget::~StartWidget()
{}

void StartWidget::waitUntilVideoEnded()
{
	if (m_videoEnded) {
		return;
	}

	QEventLoop loop;
	m_videoLoop = &loop;
	loop.exec();
	m_videoLoop = nullptr;
}

bool StartWidget::hasClosed() const
{
	return m_closeFinishedEmitted;
}

void StartWidget::onSpineReady()
{
	FINE_DEBUG_OUTPUT("[StartWidget] spine ready");
	m_spineReady = true;
	tryClose();
}

void StartWidget::onAppReady()
{
	FINE_DEBUG_OUTPUT("[StartWidget] app ready");
	m_appReady = true;
	tryClose();
}

void StartWidget::onBackendConnected()
{
	FINE_DEBUG_OUTPUT("[StartWidget] backend connected");
	m_backendReady = true;
	tryClose();
}

void StartWidget::onBackendFailed()
{
	FINE_DEBUG_OUTPUT("[StartWidget] backend failed");
	m_backendFailed = true;
	tryClose();
}

void StartWidget::onEscapePressed()
{
	if (m_closing) {
		return;
	}

	FINE_DEBUG_OUTPUT("[StartWidget] ESC pressed, dismiss immediately");
	m_closing = true;
	m_preloading = false;

	if (m_playbackTimer) {
		m_playbackTimer->stop();
	}
	if (m_typeTimer) {
		m_typeTimer->stop();
	}
	if (m_closeAnim) {
		m_closeAnim->stop();
	}
	if (m_player) {
		m_player->stop();
	}

	markVideoEnded();
	finishClose();
}

void StartWidget::showEvent(QShowEvent* event)
{
	QWidget::showEvent(event);
	activateWindow();
	setFocus(Qt::ActiveWindowFocusReason);
}

void StartWidget::onVideoFrame(const QVideoFrame& frame)
{
	if (!m_preloading || !frame.isValid()) {
		return;
	}

	++m_decodeIndex;
	if (!shouldKeepFrame(frame)) {
		return;
	}

	QImage image = frame.toImage();
	if (image.isNull()) {
		return;
	}

	if (image.format() != QImage::Format_ARGB32_Premultiplied
		&& image.format() != QImage::Format_ARGB32
		&& image.format() != QImage::Format_RGBA8888_Premultiplied
		&& image.format() != QImage::Format_RGBA8888) {
		image = image.convertToFormat(QImage::Format_ARGB32_Premultiplied);
	}

	if (!m_loggedAlpha) {
		m_loggedAlpha = true;
		FINE_DEBUG_OUTPUT(QString("[StartWidget] first frame format=%1 hasAlpha=%2 size=%3x%4")
			.arg(static_cast<int>(image.format()))
			.arg(image.hasAlphaChannel() ? "true" : "false")
			.arg(image.width())
			.arg(image.height()));
	}

	// 预解码：缩放到窗口尺寸后入缓存，不上屏（避免分层窗逐帧重绘卡死）
	m_frames.push_back(makeDisplayFrame(image));
}

bool StartWidget::shouldKeepFrame(const QVideoFrame& frame)
{
	const int maxFrames = maxCacheFrames();
	if (m_frames.size() >= maxFrames) {
		return false;
	}

	const qint64 startTimeUs = frame.startTime();
	if (startTimeUs >= 0) {
		if (m_frames.isEmpty()) {
			m_nextKeepTimeUs = startTimeUs + (1000000 / m_startupFps);
			return true;
		}
		if (startTimeUs < m_nextKeepTimeUs) {
			return false;
		}
		m_nextKeepTimeUs = startTimeUs + (1000000 / m_startupFps);
		return true;
	}

	// startTime 无效时：按约 60fps 源片相对目标 fps 隔帧取样
	const int stride = qMax(1, qRound(60.0 / m_startupFps));
	return ((m_decodeIndex - 1) % stride) == 0;
}

int StartWidget::maxCacheFrames() const
{
	if (!m_player) {
		return 1;
	}
	const qint64 durationMs = m_player->duration();
	if (durationMs <= 0) {
		return 1000000; // duration 未知时先不硬截断，靠时间戳抽帧
	}
	return qMax(1, qRound(static_cast<double>(durationMs) * m_startupFps / 1000.0));
}

void StartWidget::onDecodeFinished()
{
	if (!m_preloading) {
		return;
	}
	m_preloading = false;

	const qint64 durationMs = m_player->duration();
	m_player->stop();
	m_player->setSource(QUrl());

	FINE_DEBUG_OUTPUT(QString("[StartWidget] decode finished, startupFps=%1 cachedFrames=%2 maxFrames=%3 durationMs=%4 decodeMs=%5 frameSize=%6x%7")
		.arg(m_startupFps)
		.arg(m_frames.size())
		.arg(durationMs > 0 ? qMax(1, qRound(static_cast<double>(durationMs) * m_startupFps / 1000.0)) : -1)
		.arg(durationMs)
		.arg(m_decodeTimer.isValid() ? m_decodeTimer.elapsed() : -1)
		.arg(m_frames.isEmpty() ? 0 : m_frames.first().width())
		.arg(m_frames.isEmpty() ? 0 : m_frames.first().height()));

	if (m_frames.isEmpty()) {
		ERROR_DEBUG_OUTPUT("[StartWidget] no frames decoded; skip animation");
		switchToHoldImage();
		markVideoEnded();
		return;
	}

	startCachedPlayback(durationMs);
}

void StartWidget::startCachedPlayback(qint64 durationMs)
{
	m_frameIndex = 0;
	if (durationMs <= 0) {
		durationMs = qRound(1000.0 * m_frames.size() / 60.0);
	}
	const int intervalMs = qMax(1, qRound(static_cast<double>(durationMs) / m_frames.size()));
	FINE_DEBUG_OUTPUT(QString("[StartWidget] cached playback startupFps=%1 frames=%2 intervalMs=%3")
		.arg(m_startupFps)
		.arg(m_frames.size())
		.arg(intervalMs));

	m_frame = m_frames.first();
	update();

	m_playbackElapsed.start();
	m_playbackTimer->start(intervalMs);
}

void StartWidget::onPlaybackTick()
{
	++m_frameIndex;
	if (m_frameIndex >= m_frames.size()) {
		m_playbackTimer->stop();
		switchToHoldImage();
		markVideoEnded();
		return;
	}

	m_frame = m_frames[m_frameIndex];
	update();
}

void StartWidget::loadHoldImage()
{
	const QString configuredPath = GET_STRING_FROM_JSON(_global_config, "settings", "start_up_image_path");
	const QFileInfo imageInfo(configuredPath);
	FINE_DEBUG_OUTPUT(QString("[StartWidget] hold image path config='%1' absolute='%2' exists=%3")
		.arg(configuredPath)
		.arg(imageInfo.absoluteFilePath())
		.arg(imageInfo.exists() ? "true" : "false"));

	if (configuredPath.isEmpty() || !imageInfo.exists()) {
		ERROR_DEBUG_OUTPUT("[StartWidget] startup hold image missing");
		return;
	}

	QImage loaded(imageInfo.absoluteFilePath());
	if (loaded.isNull()) {
		ERROR_DEBUG_OUTPUT("[StartWidget] failed to load startup hold image");
		return;
	}

	m_holdImage = makeDisplayFrame(loaded);
	FINE_DEBUG_OUTPUT(QString("[StartWidget] hold image ready size=%1x%2")
		.arg(m_holdImage.width())
		.arg(m_holdImage.height()));
}

void StartWidget::switchToHoldImage()
{
	if (!m_holdImage.isNull()) {
		m_frame = m_holdImage;
	} else if (!m_frames.isEmpty()) {
		m_frame = m_frames.last();
	}
	// 同步上屏后再退出事件循环 / 释放缓存，避免异步 update 来不及绘制
	repaint();
	m_frames.clear();
	startStartupText();
}

void StartWidget::startStartupText()
{
	stopStartupText();

	m_startupLines = QStringList{
		GET_STRING_FROM_JSON(_global_dict, "formed_text", "start_up_text_0"),
		GET_STRING_FROM_JSON(_global_dict, "formed_text", "start_up_text_1"),
		GET_STRING_FROM_JSON(_global_dict, "formed_text", "start_up_text_2")
	};
	m_visibleLines = QStringList{ QString(), QString(), QString(), QString() };
	m_typeLine = 0;
	m_typeCol = 0;
	m_dotsIndex = 0;
	m_waitingLineGap = false;
	m_showingDots = false;
	m_introFinished = false;

	FINE_DEBUG_OUTPUT("[StartWidget] start typewriter text");
	m_typeTimer->start(40);
}

void StartWidget::onTypewriterTick()
{
	if (m_closing || m_startupLines.isEmpty()) {
		stopStartupText();
		return;
	}

	if (m_showingDots) {
		static const char* const kDots[] = { ".", "..", "..." };
		m_dotsIndex = (m_dotsIndex + 1) % 3;
		m_visibleLines[3] = QLatin1String(kDots[m_dotsIndex]);
		update();
		// 开场必须走完一轮 . → .. → ...，之后才允许按加载条件关闭
		if (!m_introFinished && m_dotsIndex == 2) {
			m_introFinished = true;
			FINE_DEBUG_OUTPUT("[StartWidget] intro dots cycle finished");
			tryClose();
		}
		return;
	}

	if (m_waitingLineGap) {
		m_waitingLineGap = false;
		if (m_typeLine >= m_startupLines.size()) {
			startLoadingDots();
			return;
		}
		m_typeTimer->setInterval(50);
	}

	if (m_typeLine >= m_startupLines.size()) {
		startLoadingDots();
		return;
	}

	const QString& fullLine = m_startupLines[m_typeLine];
	if (m_typeCol < fullLine.size()) {
		m_visibleLines[m_typeLine].append(fullLine.at(m_typeCol));
		++m_typeCol;
		update();
		return;
	}

	// 当前行打完：行间停顿；若已是最后一行，停顿后进入加载点循环
	m_waitingLineGap = true;
	m_typeTimer->setInterval(800);
	++m_typeLine;
	m_typeCol = 0;
}

void StartWidget::startLoadingDots()
{
	m_showingDots = true;
	m_dotsIndex = 0;
	if (m_visibleLines.size() < 4) {
		while (m_visibleLines.size() < 4) {
			m_visibleLines.append(QString());
		}
	}
	m_visibleLines[3] = QStringLiteral(".");
	m_typeTimer->setInterval(500);
	if (!m_typeTimer->isActive()) {
		m_typeTimer->start(500);
	}
	update();
	FINE_DEBUG_OUTPUT("[StartWidget] start loading dots");
}

void StartWidget::stopStartupText()
{
	if (m_typeTimer) {
		m_typeTimer->stop();
	}
	m_waitingLineGap = false;
	m_showingDots = false;
}

void StartWidget::markVideoEnded()
{
	if (m_videoEnded) {
		return;
	}
	m_videoEnded = true;
	FINE_DEBUG_OUTPUT(QString("[StartWidget] video ended, playbackMs=%1")
		.arg(m_playbackElapsed.isValid() ? m_playbackElapsed.elapsed() : 0));
	if (m_videoLoop) {
		m_videoLoop->quit();
	}
	tryClose();
}

void StartWidget::tryClose()
{
	if (m_closing || !m_introFinished) {
		return;
	}
	if (m_backendFailed) {
		FINE_DEBUG_OUTPUT("[StartWidget] tryClose backend failed after intro");
		startCloseScaleAnimation();
		return;
	}
	if (!(m_spineReady && m_appReady && m_backendReady)) {
		FINE_DEBUG_OUTPUT(QString("[StartWidget] tryClose waiting spine=%1 app=%2 backend=%3")
			.arg(m_spineReady ? "true" : "false")
			.arg(m_appReady ? "true" : "false")
			.arg(m_backendReady ? "true" : "false"));
		return;
	}
	startCloseScaleAnimation();
}

void StartWidget::startCloseScaleAnimation()
{
	m_closing = true;
	stopStartupText();
	FINE_DEBUG_OUTPUT("[StartWidget] start close scale animation");

	if (!m_closeAnim) {
		m_closeAnim = new QVariantAnimation(this);
		m_closeAnim->setDuration(150);
		m_closeAnim->setStartValue(1.0);
		m_closeAnim->setEndValue(0.0);
		m_closeAnim->setEasingCurve(QEasingCurve::Linear);
		connect(m_closeAnim, &QVariantAnimation::valueChanged, this, [this](const QVariant& value) {
			m_closeScaleY = value.toReal();
			update();
		});
		connect(m_closeAnim, &QVariantAnimation::finished, this, &StartWidget::finishClose);
	}

	m_closeScaleY = 1.0;
	m_closeAnim->stop();
	m_closeAnim->start();
}

void StartWidget::finishClose()
{
	if (m_closeFinishedEmitted) {
		return;
	}
	m_closeFinishedEmitted = true;
	FINE_DEBUG_OUTPUT("[StartWidget] closing splash");
	stopStartupText();
	m_frames.clear();
	m_holdImage = QImage();
	m_frame = QImage();
	m_visibleLines.clear();
	emit closeFinished();
	close();
	deleteLater();
}

QImage StartWidget::makeDisplayFrame(const QImage& source) const
{
	const QSize target = size();
	if (target.isEmpty() || source.isNull()) {
		return source;
	}

	const QRect crop = sourceCropRect(source.size(), target);
	if (crop.isEmpty()) {
		return source.scaled(target, Qt::IgnoreAspectRatio, Qt::FastTransformation);
	}

	return source.copy(crop).scaled(target, Qt::IgnoreAspectRatio, Qt::FastTransformation);
}

QRect StartWidget::sourceCropRect(const QSize& frameSize, const QSize& targetSize)
{
	if (frameSize.isEmpty() || targetSize.isEmpty()) {
		return QRect();
	}

	const qreal frameAspect = static_cast<qreal>(frameSize.width()) / frameSize.height();
	const qreal targetAspect = static_cast<qreal>(targetSize.width()) / targetSize.height();

	if (frameAspect > targetAspect) {
		const int cropWidth = qRound(frameSize.height() * targetAspect);
		const int x = (frameSize.width() - cropWidth) / 2;
		return QRect(x, 0, cropWidth, frameSize.height());
	}

	const int cropHeight = qRound(frameSize.width() / targetAspect);
	const int y = (frameSize.height() - cropHeight) / 2;
	return QRect(0, y, frameSize.width(), cropHeight);
}

void StartWidget::paintEvent(QPaintEvent* event)
{
	Q_UNUSED(event);
	if (m_frame.isNull()) {
		return;
	}

	QPainter painter(this);
	painter.setCompositionMode(QPainter::CompositionMode_SourceOver);
	painter.translate(0, height() * 0.5);
	painter.scale(1.0, m_closeScaleY);
	painter.translate(0, -height() * 0.5);
	painter.drawImage(rect(), m_frame);

	if (!m_visibleLines.isEmpty()) {
		painter.setFont(m_startupFont);
		painter.setRenderHint(QPainter::Antialiasing, true);
		const QFontMetrics fm(m_startupFont);
		const int lineStep = qRound(fm.height() * 1.4);
		const int originX = qRound(width() * 0.7 / 5.0);
		const int originY = qRound(height() * 1.33 / 5.0) + fm.ascent();
		const QColor outlineColor(44, 69, 99);
		const QColor fillColor(Qt::white);
		constexpr int outlineOffset = 1;
		for (int i = 0; i < m_visibleLines.size(); ++i) {
			if (m_visibleLines[i].isEmpty()) {
				continue;
			}
			const int y = originY + i * lineStep;
			painter.setPen(outlineColor);
			for (int dx = -outlineOffset; dx <= outlineOffset; ++dx) {
				for (int dy = -outlineOffset; dy <= outlineOffset; ++dy) {
					if (dx == 0 && dy == 0) {
						continue;
					}
					painter.drawText(originX + dx, y + dy, m_visibleLines[i]);
				}
			}
			painter.setPen(fillColor);
			painter.drawText(originX, y, m_visibleLines[i]);
		}
	}
}
