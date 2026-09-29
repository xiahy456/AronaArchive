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


#ifndef SCREENCAPTURE_H
#define SCREENCAPTURE_H

#include <QList>
#include <QString>
#include <QWidget>

class QScreen;

namespace ScreenCapture {

struct Frame {
	QString jpegBase64;
	int originX = 0;
	int originY = 0;
	int physW = 0;
	int physH = 0;
	int imgW = 0;
	int imgH = 0;
	qreal dpiScale = 1.0;
	int cursorX = 0;
	int cursorY = 0;
	bool ok = false;
};

// Grab a screen as JPEG plus geometry. If screen is null, use the screen under
// the cursor (then primary). excludeWindows are omitted via WDA_EXCLUDEFROMCAPTURE.
// compress=true downscales to 1280px wide and encodes JPEG quality 70;
// compress=false keeps native resolution at JPEG quality 95.
// drawCursor=true annotates the JPEG for computer-use vision: a 100/200px
// coordinate grid, then a hollow crosshair at the pointer hotspot.
// Chat screenshots leave this false.
Frame grabFrame(const QList<QWidget*>& excludeWindows, QScreen* screen = nullptr,
	bool compress = false, bool drawCursor = false);

// Grab the screen under the cursor as JPEG base64. Empty string on failure.
QString grabJpegBase64(const QList<QWidget*>& excludeWindows, bool compress = false);

}

#endif // SCREENCAPTURE_H
