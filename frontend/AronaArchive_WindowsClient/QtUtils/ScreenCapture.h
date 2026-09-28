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
