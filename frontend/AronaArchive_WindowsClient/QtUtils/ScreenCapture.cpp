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

#include "ScreenCapture.h"
#include "Defines.h"

#include <QApplication>
#include <QBuffer>
#include <QColor>
#include <QCursor>
#include <QFont>
#include <QIODevice>
#include <QGuiApplication>
#include <QImage>
#include <QPainter>
#include <QPen>
#include <QPixmap>
#include <QRect>
#include <QScreen>
#include <QThread>

#ifdef Q_OS_WIN
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <dwmapi.h>
#ifndef WDA_EXCLUDEFROMCAPTURE
#define WDA_EXCLUDEFROMCAPTURE 0x00000011
#endif
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "dwmapi.lib")
#endif

namespace ScreenCapture {

#ifdef Q_OS_WIN
class ExcludeFromCaptureGuard
{
public:
	explicit ExcludeFromCaptureGuard(const QList<QWidget*>& widgets)
	{
		for (QWidget* widget : widgets) {
			if (!widget || !widget->isVisible()) {
				continue;
			}
			HWND hwnd = reinterpret_cast<HWND>(widget->winId());
			if (!hwnd) {
				continue;
			}
			const BOOL ok = SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE);
			m_hwnds.append(hwnd);
			m_applied.append(ok);
			if (!ok) {
				ERROR_DEBUG_OUTPUT(QString("[Screen Capture] WDA_EXCLUDEFROMCAPTURE failed hwnd=%1 err=%2")
					.arg(reinterpret_cast<quintptr>(hwnd))
					.arg(GetLastError()));
			}
		}
		DwmFlush();
		QApplication::processEvents();
		QThread::msleep(16);
	}

	~ExcludeFromCaptureGuard()
	{
		for (int i = 0; i < m_hwnds.size(); ++i) {
			if (m_applied.at(i)) {
				SetWindowDisplayAffinity(m_hwnds.at(i), WDA_NONE);
			}
		}
	}

private:
	QList<HWND> m_hwnds;
	QList<BOOL> m_applied;
};
#endif

namespace {

void ensurePaintable(QImage* image)
{
	if (!image || image->isNull()) {
		return;
	}
	if (image->format() != QImage::Format_RGB32
		&& image->format() != QImage::Format_ARGB32
		&& image->format() != QImage::Format_ARGB32_Premultiplied) {
		*image = image->convertToFormat(QImage::Format_RGB32);
	}
}

void drawOutlinedText(QPainter* painter, const QRect& rect, const QString& text)
{
	for (int dx = -1; dx <= 1; ++dx) {
		for (int dy = -1; dy <= 1; ++dy) {
			if (dx == 0 && dy == 0) {
				continue;
			}
			painter->setPen(QColor(0, 0, 0, 210));
			painter->drawText(rect.translated(dx, dy), Qt::AlignLeft | Qt::AlignVCenter, text);
		}
	}
	painter->setPen(QColor(0, 230, 255, 235));
	painter->drawText(rect, Qt::AlignLeft | Qt::AlignVCenter, text);
}

void drawCoordinateGrid(QImage* image)
{
	if (!image || image->isNull()) {
		return;
	}
	ensurePaintable(image);
	const int imgW = image->width();
	const int imgH = image->height();
	if (imgW <= 0 || imgH <= 0) {
		return;
	}

	constexpr int kMinor = 100;
	constexpr int kMajor = 200;
	const int fontPx = qBound(10, imgW / 90, 18);
	const int labelH = fontPx + 4;
	const int labelW = fontPx * 6;

	QPainter painter(image);
	painter.setRenderHint(QPainter::Antialiasing, false);
	QFont font = painter.font();
	font.setPixelSize(fontPx);
	font.setBold(true);
	painter.setFont(font);

	const auto drawVLine = [&](int x, bool major) {
		const int alpha = major ? 110 : 50;
		const int width = major ? 2 : 1;
		painter.setPen(QPen(QColor(0, 0, 0, 80), width));
		painter.drawLine(x + 1, 0, x + 1, imgH - 1);
		painter.setPen(QPen(QColor(0, 220, 255, alpha), width));
		painter.drawLine(x, 0, x, imgH - 1);
	};
	const auto drawHLine = [&](int y, bool major) {
		const int alpha = major ? 110 : 50;
		const int width = major ? 2 : 1;
		painter.setPen(QPen(QColor(0, 0, 0, 80), width));
		painter.drawLine(0, y + 1, imgW - 1, y + 1);
		painter.setPen(QPen(QColor(0, 220, 255, alpha), width));
		painter.drawLine(0, y, imgW - 1, y);
	};

	for (int x = 0; x < imgW; x += kMinor) {
		drawVLine(x, (x % kMajor) == 0);
	}
	for (int y = 0; y < imgH; y += kMinor) {
		drawHLine(y, (y % kMajor) == 0);
	}

	for (int x = 0; x < imgW; x += kMajor) {
		drawOutlinedText(&painter, QRect(x + 3, 2, labelW, labelH), QString::number(x));
	}
	for (int y = kMajor; y < imgH; y += kMajor) {
		drawOutlinedText(&painter, QRect(3, y - labelH / 2, labelW, labelH), QString::number(y));
	}
}

void drawCursorCrosshair(
	QImage* image,
	int originX,
	int originY,
	int physW,
	int physH,
	int cursorX,
	int cursorY)
{
	if (!image || image->isNull() || physW <= 0 || physH <= 0) {
		return;
	}
	const int imgW = image->width();
	const int imgH = image->height();
	if (imgW <= 0 || imgH <= 0) {
		return;
	}
	const int imgX = qRound(static_cast<double>(cursorX - originX) * imgW / physW);
	const int imgY = qRound(static_cast<double>(cursorY - originY) * imgH / physH);
	if (imgX < 0 || imgY < 0 || imgX >= imgW || imgY >= imgH) {
		return;
	}

	ensurePaintable(image);

	const int arm = qMax(18, imgW / 80);
	const int gap = qMax(4, arm / 5);
	const int ringR = qMax(6, arm / 4);
	const int thickOuter = qMax(3, arm / 10);
	const int thickInner = qMax(1, thickOuter - 2);

	QPainter painter(image);
	painter.setRenderHint(QPainter::Antialiasing, true);
	painter.setBrush(Qt::NoBrush);

	const auto stroke = [&](const QColor& color, int width) {
		QPen pen(color, width, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin);
		painter.setPen(pen);
		painter.drawEllipse(QPoint(imgX, imgY), ringR, ringR);
		painter.drawLine(QPoint(imgX, imgY - arm), QPoint(imgX, imgY - gap));
		painter.drawLine(QPoint(imgX, imgY + gap), QPoint(imgX, imgY + arm));
		painter.drawLine(QPoint(imgX - arm, imgY), QPoint(imgX - gap, imgY));
		painter.drawLine(QPoint(imgX + gap, imgY), QPoint(imgX + arm, imgY));
	};
	stroke(QColor(0, 0, 0), thickOuter);
	stroke(QColor(255, 0, 220), thickInner);
}

}

Frame grabFrame(const QList<QWidget*>& excludeWindows, QScreen* screen, bool compress, bool drawCursor)
{
	Frame frame;

#ifdef Q_OS_WIN
	ExcludeFromCaptureGuard guard(excludeWindows);
#else
	Q_UNUSED(excludeWindows);
#endif

	if (!screen) {
		screen = QGuiApplication::screenAt(QCursor::pos());
	}
	if (!screen) {
		screen = QGuiApplication::primaryScreen();
	}
	if (!screen) {
		ERROR_DEBUG_OUTPUT("[Screen Capture] No screen available");
		return frame;
	}

	const QRect geo = screen->geometry();
	frame.originX = geo.x();
	frame.originY = geo.y();
	frame.physW = geo.width();
	frame.physH = geo.height();
	frame.dpiScale = screen->devicePixelRatio();
	const QPoint cursor = QCursor::pos();
	frame.cursorX = cursor.x();
	frame.cursorY = cursor.y();

	const QPixmap pixmap = screen->grabWindow(0);
	if (pixmap.isNull()) {
		ERROR_DEBUG_OUTPUT("[Screen Capture] grabWindow returned null");
		return frame;
	}

	const qreal pixmapDpr = pixmap.devicePixelRatio();
	QImage image = pixmap.toImage();
	image.setDevicePixelRatio(1.0);
	const int jpegQuality = compress ? 70 : 95;
	if (compress) {
		const int maxWidth = 1280;
		if (image.width() > maxWidth) {
			image = image.scaledToWidth(maxWidth, Qt::SmoothTransformation);
			image.setDevicePixelRatio(1.0);
		}
	}
	if (drawCursor) {
		drawCoordinateGrid(&image);
		drawCursorCrosshair(
			&image,
			frame.originX,
			frame.originY,
			frame.physW,
			frame.physH,
			frame.cursorX,
			frame.cursorY);
	}

	QByteArray bytes;
	QBuffer buffer(&bytes);
	buffer.open(QIODevice::WriteOnly);
	if (!image.save(&buffer, "JPEG", jpegQuality)) {
		ERROR_DEBUG_OUTPUT("[Screen Capture] JPEG encode failed");
		return frame;
	}

	frame.imgW = image.width();
	frame.imgH = image.height();
	frame.jpegBase64 = QString::fromLatin1(bytes.toBase64());
	frame.ok = !frame.jpegBase64.isEmpty() && frame.physW > 0 && frame.physH > 0
		&& frame.imgW > 0 && frame.imgH > 0;

	FINE_DEBUG_OUTPUT(QString("[Screen Capture] Captured %1x%2 jpeg=%3 bytes origin=%4,%5 phys=%6x%7 compress=%8 cursor=%9 pixmapDpr=%10 imageDpr=%11")
		.arg(frame.imgW)
		.arg(frame.imgH)
		.arg(bytes.size())
		.arg(frame.originX)
		.arg(frame.originY)
		.arg(frame.physW)
		.arg(frame.physH)
		.arg(compress ? "true" : "false")
		.arg(drawCursor ? "true" : "false")
		.arg(pixmapDpr, 0, 'f', 2)
		.arg(image.devicePixelRatio(), 0, 'f', 2));
	return frame;
}

QString grabJpegBase64(const QList<QWidget*>& excludeWindows, bool compress)
{
	return grabFrame(excludeWindows, nullptr, compress).jpegBase64;
}

}
