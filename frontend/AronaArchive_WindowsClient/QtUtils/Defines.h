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

#ifndef DEFINES_H
#define DEFINES_H

#include "DebugManager.h"

// 可爱的qDebug正常输出前缀
#define FINE_PR "ദ്ദി˶˃ ᵕ ˂ )✧\t"

// 可爱的qWarning、qCritical错误输出前缀
#define ERROR_PR "૮₍ ˶•‸•˶₎ა  \t"

// 获取Json->Json->String
#define GET_STRING_FROM_JSON(global_json, sec_json, trd_string) global_json->getJson(sec_json).getString(trd_string)

// 获取Json->Json->int
#define GET_INT_FROM_JSON(global_json, sec_json, trd_int) global_json->getJson(sec_json).getInt(trd_int)

// 获取Json->Json->double
#define GET_DOUBLE_FROM_JSON(global_json, sec_json, trd_double) global_json->getJson(sec_json).getDouble(trd_double)

// 获取Json->Json->bool
#define GET_BOOL_FROM_JSON(global_json, sec_json, trd_bool) global_json->getJson(sec_json).getBool(trd_bool)

// 修改Json->Json->String
#define SET_STRING_TO_JSON(global_json, sec_key, trd_key, val) global_json->setStringInJson(sec_key, trd_key, val)

// 修改Json->Json->int
#define SET_INT_TO_JSON(global_json, sec_key, trd_key, val) global_json->setIntInJson(sec_key, trd_key, val)

// 修改Json->Json->double
#define SET_DOUBLE_TO_JSON(global_json, sec_key, trd_key, val) global_json->setDoubleInJson(sec_key, trd_key, val)

// 修改Json->Json->bool
#define SET_BOOL_TO_JSON(global_json, sec_key, trd_key, val) global_json->setBoolInJson(sec_key, trd_key, val)

// 获取全局缩放比例
#define WIDGET_ZOOM GET_DOUBLE_FROM_JSON(_global_config, "settings", "zoom")

// 正常调试输出
#define FINE_DEBUG_OUTPUT(_text) do { \
	qDebug().noquote() << FINE_PR << _text; \
	DebugManager::instance()->sendDebugMessage(QString(FINE_PR) + _text, __FUNCTION__); \
} while(0)

// 错误调试输出
#define ERROR_DEBUG_OUTPUT(_text) do { \
	qWarning().noquote() << ERROR_PR << _text; \
	DebugManager::instance()->sendDebugMessage(QString(ERROR_PR) + _text, __FUNCTION__); \
} while(0)

// OpenGL初始化：半透明 overlay 用 2x MSAA，交换缓冲区对齐 vsync
#define OPENGL_INITIALLIZE do { \
	QSurfaceFormat format; \
	format.setAlphaBufferSize(8); \
	format.setSamples(2); \
	format.setSwapInterval(1); \
	QSurfaceFormat::setDefaultFormat(format); \
} while(0)

// 应用程序相关初始化设置
#define APPLICATION_INITIALLIZE do { \
	app.setApplicationName(GET_STRING_FROM_JSON(_global_dict, "application_data", "application_name")); /*设置应用程序名称*/ \
	app.setApplicationVersion("0.0.1"); /*设置应用程序版本*/ \
	app.setWindowIcon(QIcon(GET_STRING_FROM_JSON(_global_config, "settings", "icon_path")));    /*设置应用程序图标*/ \
	app.setQuitOnLastWindowClosed(false);   /*设置当最后一个窗口关闭时不退出应用程序*/ \
	qputenv("QT_FRAME_RATE_OVERRIDE", QByteArray::number(GET_INT_FROM_JSON(_global_config, "settings", "frame_rate")));    /*设置全局帧率*/ \
} while(0)

#endif // !DEFINES_H

