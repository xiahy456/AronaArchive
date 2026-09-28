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

#include "ComputerUseExecutor.h"
#include "Defines.h"
#include "GlobalVariables.h"
#include "ScreenCapture.h"

#include <QCoreApplication>
#include <QCursor>
#include <QEventLoop>
#include <QGuiApplication>
#include <QPoint>
#include <QScreen>
#include <QThread>
#include <QVector>

#ifdef Q_OS_WIN
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#pragma comment(lib, "user32.lib")
#endif

namespace {

constexpr int kSettleMs = 16;
constexpr int kDefaultClickSettleMs = 2000;
constexpr int kDragMaxSteps = 24;
constexpr int kDragStepMs = 8;
constexpr int kDragPixelsPerStep = 40;
constexpr int kScrollDyLimit = 8;

bool screenshotCompressEnabled()
{
	return GET_BOOL_FROM_JSON(_global_config, "computer_use", "compress_screenshot");
}

int clickSettleMs()
{
	const QJsonObject obj = _global_config->getJson(QStringLiteral("computer_use")).m_jsonObj;
	const QString key = QStringLiteral("click_settle_ms");
	if (!obj.contains(key)) {
		return kDefaultClickSettleMs;
	}
	const int ms = obj.value(key).toInt(-1);
	if (ms < 0) {
		return kDefaultClickSettleMs;
	}
	return ms;
}

bool isClickAction(const QString& name)
{
	return name == QLatin1String("click")
		|| name == QLatin1String("double_click")
		|| name == QLatin1String("right_click")
		|| name == QLatin1String("middle_click");
}

#ifdef Q_OS_WIN
WORD virtualKeyFromName(const QString& name)
{
	const QString key = name.trimmed().toLower();
	if (key == QLatin1String("escape") || key == QLatin1String("esc")) return VK_ESCAPE;
	if (key == QLatin1String("win") || key == QLatin1String("super") || key == QLatin1String("meta")) {
		return VK_LWIN;
	}
	if (key == QLatin1String("ctrl") || key == QLatin1String("control")) return VK_CONTROL;
	if (key == QLatin1String("alt")) return VK_MENU;
	if (key == QLatin1String("shift")) return VK_SHIFT;
	if (key == QLatin1String("enter") || key == QLatin1String("return")) return VK_RETURN;
	if (key == QLatin1String("tab")) return VK_TAB;
	if (key == QLatin1String("space")) return VK_SPACE;
	if (key == QLatin1String("backspace")) return VK_BACK;
	if (key == QLatin1String("delete") || key == QLatin1String("del")) return VK_DELETE;
	if (key == QLatin1String("up")) return VK_UP;
	if (key == QLatin1String("down")) return VK_DOWN;
	if (key == QLatin1String("left")) return VK_LEFT;
	if (key == QLatin1String("right")) return VK_RIGHT;
	if (key == QLatin1String("home")) return VK_HOME;
	if (key == QLatin1String("end")) return VK_END;
	if (key.size() == 1) {
		const QChar ch = key.at(0).toUpper();
		if (ch >= QLatin1Char('A') && ch <= QLatin1Char('Z')) {
			return static_cast<WORD>(ch.unicode());
		}
		if (ch >= QLatin1Char('0') && ch <= QLatin1Char('9')) {
			return static_cast<WORD>(ch.unicode());
		}
	}
	return 0;
}

bool sendKeyboardVk(WORD vk, bool down)
{
	INPUT input{};
	input.type = INPUT_KEYBOARD;
	input.ki.wVk = vk;
	input.ki.dwFlags = down ? 0 : KEYEVENTF_KEYUP;
	return SendInput(1, &input, sizeof(INPUT)) == 1;
}
#endif

}

ComputerUseExecutor::ComputerUseExecutor(QObject* parent)
	: QObject(parent)
	, m_delayTimer(new QTimer(this))
{
	m_delayTimer->setSingleShot(true);
	connect(m_delayTimer, &QTimer::timeout, this, [this]() {
		if (m_cancelled) {
			m_busy = false;
			return;
		}
		captureAndFinish(m_pendingOk, m_pendingError);
	});
}

void ComputerUseExecutor::setExcludeWindows(const QList<QWidget*>& widgets)
{
	m_excludeWindows.clear();
	for (QWidget* widget : widgets) {
		m_excludeWindows.append(widget);
	}
}

void ComputerUseExecutor::cancel()
{
	m_cancelled = true;
	m_delayTimer->stop();
	releaseButtons();
	m_busy = false;
}

bool ComputerUseExecutor::isBusy() const
{
	return m_busy;
}

void ComputerUseExecutor::execute(const QJsonObject& action)
{
	if (m_busy) {
		ERROR_DEBUG_OUTPUT("[Computer Use] Rejected action: executor busy");
		return;
	}

	m_cancelled = false;
	m_runId = action.value(QStringLiteral("run_id")).toString();
	m_step = action.value(QStringLiteral("step")).toInt();
	lockScreenForRun(m_runId);

	QString error;
	const QString name = action.value(QStringLiteral("action")).toString().trimmed().toLower();
	if (name == QLatin1String("wait")) {
		int ms = action.value(QStringLiteral("ms")).toInt();
		if (ms < 0) {
			finish(false, QStringLiteral("invalid_wait"));
			return;
		}
		m_busy = true;
		scheduleCapture(ms, true, QString());
		return;
	}

	m_busy = true;
	const bool ok = performAction(action, &error);
	if (!ok) {
		scheduleCapture(kSettleMs, false, error);
		return;
	}
	const int settleMs = isClickAction(name) ? clickSettleMs() : kSettleMs;
	scheduleCapture(settleMs, true, QString());
}

void ComputerUseExecutor::scheduleCapture(int delayMs, bool ok, const QString& error)
{
	m_pendingOk = ok;
	m_pendingError = error;
	m_delayTimer->start(qMax(0, delayMs));
}

void ComputerUseExecutor::finish(bool ok, const QString& error)
{
	captureAndFinish(ok, error);
}

void ComputerUseExecutor::captureAndFinish(bool ok, const QString& error)
{
	m_busy = false;
	if (m_cancelled) {
		return;
	}

	QList<QWidget*> exclude;
	for (const QPointer<QWidget>& widget : m_excludeWindows) {
		if (widget) {
			exclude.append(widget.data());
		}
	}

	QScreen* screen = m_lockedScreen;
	if (!screen) {
		screen = QGuiApplication::screenAt(QCursor::pos());
	}
	const ScreenCapture::Frame frame = ScreenCapture::grabFrame(
		exclude, screen, screenshotCompressEnabled(), true);

	QJsonObject observation;
	const bool resultOk = ok && frame.ok;
	QString resultError = error;
	if (!resultOk && resultError.isEmpty()) {
		resultError = frame.ok ? QStringLiteral("failed") : QStringLiteral("capture_failed");
	}
	observation.insert(QStringLiteral("run_id"), m_runId);
	observation.insert(QStringLiteral("step"), m_step);
	observation.insert(QStringLiteral("ok"), resultOk);
	observation.insert(QStringLiteral("error"), resultError);

	QJsonObject screenObj;
	screenObj.insert(QStringLiteral("origin_x"), frame.originX);
	screenObj.insert(QStringLiteral("origin_y"), frame.originY);
	screenObj.insert(QStringLiteral("phys_w"), frame.physW);
	screenObj.insert(QStringLiteral("phys_h"), frame.physH);
	screenObj.insert(QStringLiteral("img_w"), frame.imgW);
	screenObj.insert(QStringLiteral("img_h"), frame.imgH);
	screenObj.insert(QStringLiteral("dpi_scale"), frame.dpiScale);
	screenObj.insert(QStringLiteral("cursor_x"), frame.cursorX);
	screenObj.insert(QStringLiteral("cursor_y"), frame.cursorY);
	observation.insert(QStringLiteral("screen"), screenObj);
	if (!frame.jpegBase64.isEmpty()) {
		QJsonObject image;
		image.insert(QStringLiteral("mime"), QStringLiteral("image/jpeg"));
		image.insert(QStringLiteral("data"), frame.jpegBase64);
		observation.insert(QStringLiteral("image"), image);
	}

	m_lastImgW = frame.imgW;
	m_lastImgH = frame.imgH;

	FINE_DEBUG_OUTPUT(QString("[Computer Use] Observation run=%1 step=%2 ok=%3 error=%4")
		.arg(m_runId)
		.arg(m_step)
		.arg(observation.value(QStringLiteral("ok")).toBool() ? "true" : "false")
		.arg(observation.value(QStringLiteral("error")).toString()));
	emit observationReady(observation);
}

void ComputerUseExecutor::lockScreenForRun(const QString& runId)
{
	if (!runId.isEmpty() && runId == m_lockedRunId && m_lockedScreen) {
		return;
	}
	m_lockedRunId = runId;
	m_lastImgW = 0;
	m_lastImgH = 0;
	m_lockedScreen = QGuiApplication::screenAt(QCursor::pos());
	if (!m_lockedScreen) {
		m_lockedScreen = QGuiApplication::primaryScreen();
	}
	m_lockedGeom = m_lockedScreen ? m_lockedScreen->geometry() : QRect();
	const qreal dpr = m_lockedScreen ? m_lockedScreen->devicePixelRatio() : 1.0;
	FINE_DEBUG_OUTPUT(QString("[Computer Use] Locked screen run=%1 origin=%2,%3 size=%4x%5 dpr=%6")
		.arg(runId)
		.arg(m_lockedGeom.x())
		.arg(m_lockedGeom.y())
		.arg(m_lockedGeom.width())
		.arg(m_lockedGeom.height())
		.arg(dpr, 0, 'f', 2));
}

bool ComputerUseExecutor::mapPoint(double x, double y, const QString& coordSpace, int* outX, int* outY, QString* error) const
{
	if (m_lockedGeom.isEmpty()) {
		if (error) {
			*error = QStringLiteral("no_screen");
		}
		return false;
	}
	const int originX = m_lockedGeom.x();
	const int originY = m_lockedGeom.y();
	const int physW = m_lockedGeom.width();
	const int physH = m_lockedGeom.height();
	int physX = originX;
	int physY = originY;
	const QString space = coordSpace.trimmed().toLower();
	if (space.isEmpty() || space == QLatin1String("normalized")) {
		if (x < 0.0 || x > 1.0 || y < 0.0 || y > 1.0) {
			if (error) {
				*error = QStringLiteral("out_of_bounds");
			}
			return false;
		}
		physX = originX + qRound(x * qMax(0, physW - 1));
		physY = originY + qRound(y * qMax(0, physH - 1));
	}
	else if (space == QLatin1String("image")) {
		int imgW = m_lastImgW;
		int imgH = m_lastImgH;
		if (imgW <= 0 || imgH <= 0) {
			QList<QWidget*> exclude;
			for (const QPointer<QWidget>& widget : m_excludeWindows) {
				if (widget) {
					exclude.append(widget.data());
				}
			}
			const ScreenCapture::Frame preview = ScreenCapture::grabFrame(
				exclude, m_lockedScreen, screenshotCompressEnabled());
			imgW = preview.imgW;
			imgH = preview.imgH;
		}
		if (imgW <= 0 || imgH <= 0) {
			if (error) {
				*error = QStringLiteral("no_image_size");
			}
			return false;
		}
		physX = originX + qRound(x * static_cast<double>(physW) / imgW);
		physY = originY + qRound(y * static_cast<double>(physH) / imgH);
	}
	else {
		if (error) {
			*error = QStringLiteral("unknown_coord_space");
		}
		return false;
	}

	if (physX < originX || physY < originY
		|| physX >= originX + physW || physY >= originY + physH) {
		if (error) {
			*error = QStringLiteral("out_of_bounds");
		}
		return false;
	}
	if (outX) {
		*outX = physX;
	}
	if (outY) {
		*outY = physY;
	}
	return true;
}

bool ComputerUseExecutor::performAction(const QJsonObject& action, QString* error)
{
	const QString name = action.value(QStringLiteral("action")).toString().trimmed().toLower();
	if (name == QLatin1String("done")) {
		return true;
	}

#ifndef Q_OS_WIN
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#else
	if (name == QLatin1String("move")
		|| name == QLatin1String("click")
		|| name == QLatin1String("double_click")
		|| name == QLatin1String("right_click")
		|| name == QLatin1String("middle_click")
		|| name == QLatin1String("drag")
		|| name == QLatin1String("right_drag")
		|| name == QLatin1String("scroll")) {
		if (!action.contains(QStringLiteral("x")) || !action.contains(QStringLiteral("y"))
			|| action.value(QStringLiteral("x")).isNull()
			|| action.value(QStringLiteral("y")).isNull()) {
			if (error) {
				*error = QStringLiteral("missing_coordinates");
			}
			return false;
		}
		int physX = 0;
		int physY = 0;
		if (!mapPoint(
			action.value(QStringLiteral("x")).toDouble(),
			action.value(QStringLiteral("y")).toDouble(),
			action.value(QStringLiteral("coord_space")).toString(),
			&physX,
			&physY,
			error)) {
			return false;
		}
		FINE_DEBUG_OUTPUT(QString("[Computer Use] Map action=%1 (%2,%3) space=%4 -> phys=%5,%6")
			.arg(name)
			.arg(action.value(QStringLiteral("x")).toDouble())
			.arg(action.value(QStringLiteral("y")).toDouble())
			.arg(action.value(QStringLiteral("coord_space")).toString())
			.arg(physX)
			.arg(physY));
		const bool isDrag = name == QLatin1String("drag") || name == QLatin1String("right_drag");
		if (isDrag) {
			if (!action.contains(QStringLiteral("x2")) || !action.contains(QStringLiteral("y2"))
				|| action.value(QStringLiteral("x2")).isNull()
				|| action.value(QStringLiteral("y2")).isNull()) {
				if (error) {
					*error = QStringLiteral("missing_coordinates");
				}
				return false;
			}
			int endX = 0;
			int endY = 0;
			if (!mapPoint(
				action.value(QStringLiteral("x2")).toDouble(),
				action.value(QStringLiteral("y2")).toDouble(),
				action.value(QStringLiteral("coord_space")).toString(),
				&endX,
				&endY,
				error)) {
				return false;
			}
			FINE_DEBUG_OUTPUT(QString("[Computer Use] Map action=%1 end (%2,%3) space=%4 -> phys=%5,%6")
				.arg(name)
				.arg(action.value(QStringLiteral("x2")).toDouble())
				.arg(action.value(QStringLiteral("y2")).toDouble())
				.arg(action.value(QStringLiteral("coord_space")).toString())
				.arg(endX)
				.arg(endY));
			bool dragOk = false;
			if (name == QLatin1String("drag")) {
				dragOk = sendDrag(physX, physY, endX, endY, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, error);
			} else {
				dragOk = sendDrag(physX, physY, endX, endY, MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, error);
			}
			const QPoint actual = QCursor::pos();
			FINE_DEBUG_OUTPUT(QString("[Computer Use] Cursor after drag intended=%1,%2 actual=%3,%4")
				.arg(endX)
				.arg(endY)
				.arg(actual.x())
				.arg(actual.y()));
			return dragOk;
		}
		if (!sendMouseMove(physX, physY, error)) {
			return false;
		}
		{
			const QPoint actual = QCursor::pos();
			FINE_DEBUG_OUTPUT(QString("[Computer Use] Cursor after move intended=%1,%2 actual=%3,%4")
				.arg(physX)
				.arg(physY)
				.arg(actual.x())
				.arg(actual.y()));
		}
		if (name == QLatin1String("move")) {
			return true;
		}
		if (pointHitsArona()) {
			if (error) {
				*error = QStringLiteral("hit_arona_window");
			}
			return false;
		}
		if (name == QLatin1String("click")) {
			return sendMouseButton(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, error);
		}
		if (name == QLatin1String("double_click")) {
			return sendMouseButton(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, error)
				&& sendMouseButton(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, error);
		}
		if (name == QLatin1String("right_click")) {
			return sendMouseButton(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, error);
		}
		if (name == QLatin1String("middle_click")) {
			return sendMouseButton(MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, error);
		}
		if (name == QLatin1String("scroll")) {
			if (!action.contains(QStringLiteral("dy")) || action.value(QStringLiteral("dy")).isNull()) {
				if (error) {
					*error = QStringLiteral("missing_dy");
				}
				return false;
			}
			return sendScroll(qRound(action.value(QStringLiteral("dy")).toDouble()), error);
		}
	}

	if (name == QLatin1String("key")) {
		const QString combo = action.value(QStringLiteral("combo")).toString();
		if (combo.trimmed().isEmpty()) {
			if (error) {
				*error = QStringLiteral("missing_combo");
			}
			return false;
		}
		return sendKeyCombo(combo, error);
	}

	if (name == QLatin1String("type")) {
		const QString text = action.value(QStringLiteral("text")).toString();
		if (text.isEmpty()) {
			if (error) {
				*error = QStringLiteral("missing_text");
			}
			return false;
		}
		return sendUnicodeText(text, error);
	}

	if (error) {
		*error = QStringLiteral("unknown_action");
	}
	return false;
#endif
}

bool ComputerUseExecutor::sendMouseMove(int x, int y, QString* error)
{
	if (m_lockedScreen) {
		const QPoint local(x - m_lockedGeom.x(), y - m_lockedGeom.y());
		QCursor::setPos(m_lockedScreen, local);
	} else {
		QCursor::setPos(QPoint(x, y));
	}
	Q_UNUSED(error);
	return true;
}

bool ComputerUseExecutor::sendMouseButton(int downFlag, int upFlag, QString* error)
{
#ifdef Q_OS_WIN
	INPUT inputs[2]{};
	inputs[0].type = INPUT_MOUSE;
	inputs[0].mi.dwFlags = static_cast<DWORD>(downFlag);
	inputs[1].type = INPUT_MOUSE;
	inputs[1].mi.dwFlags = static_cast<DWORD>(upFlag);
	if (downFlag == MOUSEEVENTF_LEFTDOWN) {
		m_leftDown = true;
	}
	if (downFlag == MOUSEEVENTF_RIGHTDOWN) {
		m_rightDown = true;
	}
	if (downFlag == MOUSEEVENTF_MIDDLEDOWN) {
		m_middleDown = true;
	}
	const UINT sent = SendInput(2, inputs, sizeof(INPUT));
	if (downFlag == MOUSEEVENTF_LEFTDOWN) {
		m_leftDown = false;
	}
	if (downFlag == MOUSEEVENTF_RIGHTDOWN) {
		m_rightDown = false;
	}
	if (downFlag == MOUSEEVENTF_MIDDLEDOWN) {
		m_middleDown = false;
	}
	if (sent != 2) {
		if (error) {
			*error = QStringLiteral("sendinput_failed");
		}
		return false;
	}
	return true;
#else
	Q_UNUSED(downFlag);
	Q_UNUSED(upFlag);
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#endif
}

bool ComputerUseExecutor::sendMouseDown(int downFlag, QString* error)
{
#ifdef Q_OS_WIN
	INPUT input{};
	input.type = INPUT_MOUSE;
	input.mi.dwFlags = static_cast<DWORD>(downFlag);
	if (downFlag == MOUSEEVENTF_LEFTDOWN) {
		m_leftDown = true;
	}
	if (downFlag == MOUSEEVENTF_RIGHTDOWN) {
		m_rightDown = true;
	}
	if (downFlag == MOUSEEVENTF_MIDDLEDOWN) {
		m_middleDown = true;
	}
	if (SendInput(1, &input, sizeof(INPUT)) != 1) {
		if (downFlag == MOUSEEVENTF_LEFTDOWN) {
			m_leftDown = false;
		}
		if (downFlag == MOUSEEVENTF_RIGHTDOWN) {
			m_rightDown = false;
		}
		if (downFlag == MOUSEEVENTF_MIDDLEDOWN) {
			m_middleDown = false;
		}
		if (error) {
			*error = QStringLiteral("sendinput_failed");
		}
		return false;
	}
	return true;
#else
	Q_UNUSED(downFlag);
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#endif
}

bool ComputerUseExecutor::sendMouseUp(int upFlag, QString* error)
{
#ifdef Q_OS_WIN
	INPUT input{};
	input.type = INPUT_MOUSE;
	input.mi.dwFlags = static_cast<DWORD>(upFlag);
	const UINT sent = SendInput(1, &input, sizeof(INPUT));
	if (sent == 1) {
		if (upFlag == MOUSEEVENTF_LEFTUP) {
			m_leftDown = false;
		}
		if (upFlag == MOUSEEVENTF_RIGHTUP) {
			m_rightDown = false;
		}
		if (upFlag == MOUSEEVENTF_MIDDLEUP) {
			m_middleDown = false;
		}
		return true;
	}
	if (error) {
		*error = QStringLiteral("sendinput_failed");
	}
	return false;
#else
	Q_UNUSED(upFlag);
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#endif
}

bool ComputerUseExecutor::sendDrag(int startX, int startY, int endX, int endY, int downFlag, int upFlag, QString* error)
{
#ifdef Q_OS_WIN
	if (!sendMouseMove(startX, startY, error)) {
		return false;
	}
	if (pointHitsArona()) {
		if (error) {
			*error = QStringLiteral("hit_arona_window");
		}
		return false;
	}
	if (!sendMouseDown(downFlag, error)) {
		releaseButtons();
		return false;
	}

	const int deltaX = endX - startX;
	const int deltaY = endY - startY;
	const int distance = qMax(qAbs(deltaX), qAbs(deltaY));
	const int steps = qBound(1, (distance + kDragPixelsPerStep - 1) / kDragPixelsPerStep, kDragMaxSteps);
	bool ok = true;
	QString dragError;
	for (int i = 1; i <= steps; ++i) {
		QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
		if (m_cancelled) {
			ok = false;
			dragError = QStringLiteral("cancelled");
			break;
		}
		const int x = startX + qRound(static_cast<double>(deltaX) * i / steps);
		const int y = startY + qRound(static_cast<double>(deltaY) * i / steps);
		if (!sendMouseMove(x, y, &dragError)) {
			ok = false;
			break;
		}
		if (i < steps) {
			QThread::msleep(kDragStepMs);
		}
	}
	const bool hitEnd = pointHitsArona();
	if (!sendMouseUp(upFlag, error)) {
		releaseButtons();
		return false;
	}
	if (!ok) {
		if (error) {
			*error = dragError.isEmpty() ? QStringLiteral("drag_failed") : dragError;
		}
		return false;
	}
	if (hitEnd) {
		if (error) {
			*error = QStringLiteral("hit_arona_window");
		}
		return false;
	}
	return true;
#else
	Q_UNUSED(startX);
	Q_UNUSED(startY);
	Q_UNUSED(endX);
	Q_UNUSED(endY);
	Q_UNUSED(downFlag);
	Q_UNUSED(upFlag);
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#endif
}

bool ComputerUseExecutor::sendScroll(int dy, QString* error)
{
#ifdef Q_OS_WIN
	const int clamped = qBound(-kScrollDyLimit, dy, kScrollDyLimit);
	if (clamped == 0) {
		if (error) {
			*error = QStringLiteral("invalid_dy");
		}
		return false;
	}
	INPUT input{};
	input.type = INPUT_MOUSE;
	input.mi.dwFlags = MOUSEEVENTF_WHEEL;
	input.mi.mouseData = static_cast<DWORD>(clamped * WHEEL_DELTA);
	if (SendInput(1, &input, sizeof(INPUT)) != 1) {
		if (error) {
			*error = QStringLiteral("sendinput_failed");
		}
		return false;
	}
	return true;
#else
	Q_UNUSED(dy);
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#endif
}

bool ComputerUseExecutor::sendKeyCombo(const QString& combo, QString* error)
{
#ifdef Q_OS_WIN
	const QStringList parts = combo.split(QLatin1Char('+'), Qt::SkipEmptyParts);
	if (parts.isEmpty()) {
		if (error) {
			*error = QStringLiteral("missing_combo");
		}
		return false;
	}
	QList<WORD> keys;
	for (const QString& part : parts) {
		const WORD vk = virtualKeyFromName(part);
		if (vk == 0) {
			if (error) {
				*error = QStringLiteral("unknown_key");
			}
			return false;
		}
		keys.append(vk);
	}
	for (WORD vk : keys) {
		if (!sendKeyboardVk(vk, true)) {
			if (error) {
				*error = QStringLiteral("sendinput_failed");
			}
			return false;
		}
	}
	for (int i = keys.size() - 1; i >= 0; --i) {
		sendKeyboardVk(keys.at(i), false);
	}
	return true;
#else
	Q_UNUSED(combo);
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#endif
}

bool ComputerUseExecutor::sendUnicodeText(const QString& text, QString* error)
{
#ifdef Q_OS_WIN
	QVector<INPUT> inputs;
	inputs.reserve(text.size() * 2);
	for (const QChar ch : text) {
		INPUT down{};
		down.type = INPUT_KEYBOARD;
		down.ki.wScan = ch.unicode();
		down.ki.dwFlags = KEYEVENTF_UNICODE;
		INPUT up = down;
		up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
		inputs.append(down);
		inputs.append(up);
	}
	if (inputs.isEmpty()) {
		return true;
	}
	const UINT sent = SendInput(static_cast<UINT>(inputs.size()), inputs.data(), sizeof(INPUT));
	if (sent != static_cast<UINT>(inputs.size())) {
		if (error) {
			*error = QStringLiteral("sendinput_failed");
		}
		return false;
	}
	return true;
#else
	Q_UNUSED(text);
	if (error) {
		*error = QStringLiteral("unsupported_platform");
	}
	return false;
#endif
}

bool ComputerUseExecutor::pointHitsArona() const
{
#ifdef Q_OS_WIN
	POINT pt{};
	if (!GetCursorPos(&pt)) {
		return false;
	}
	HWND hwnd = WindowFromPoint(pt);
	const HWND root = hwnd ? GetAncestor(hwnd, GA_ROOT) : nullptr;
	while (hwnd) {
		for (const QPointer<QWidget>& widget : m_excludeWindows) {
			if (!widget) {
				continue;
			}
			const HWND mine = reinterpret_cast<HWND>(widget->winId());
			if (mine && (hwnd == mine || root == mine)) {
				return true;
			}
		}
		hwnd = GetParent(hwnd);
	}
	return false;
#else
	return false;
#endif
}

void ComputerUseExecutor::releaseButtons()
{
#ifdef Q_OS_WIN
	if (m_leftDown) {
		INPUT input{};
		input.type = INPUT_MOUSE;
		input.mi.dwFlags = MOUSEEVENTF_LEFTUP;
		SendInput(1, &input, sizeof(INPUT));
		m_leftDown = false;
	}
	if (m_rightDown) {
		INPUT input{};
		input.type = INPUT_MOUSE;
		input.mi.dwFlags = MOUSEEVENTF_RIGHTUP;
		SendInput(1, &input, sizeof(INPUT));
		m_rightDown = false;
	}
	if (m_middleDown) {
		INPUT input{};
		input.type = INPUT_MOUSE;
		input.mi.dwFlags = MOUSEEVENTF_MIDDLEUP;
		SendInput(1, &input, sizeof(INPUT));
		m_middleDown = false;
	}
#endif
}
