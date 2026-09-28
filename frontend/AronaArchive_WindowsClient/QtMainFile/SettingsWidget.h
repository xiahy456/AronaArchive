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

#include <QWidget>
#include <QCloseEvent>
#include <QPropertyAnimation>
#include <QTimer>

#include "GlobalInclude.h"
#include "BlueakaFontLoader.h"

#include "ui_SettingsWidget.h"

// 获取平行四边形的width
#define WIDTH_X(_width, _height) (_width + _height*0.5773) * WIDGET_ZOOM

// 按照tan60度获取x坐标
#define POSITION_X(_start_x, _gap, _step) (_start_x - _gap*_step*0.5773) * WIDGET_ZOOM

// 获取y坐标
#define POSITION_Y(_start_y, _gap, _step) (_start_y + _gap*_step) * WIDGET_ZOOM

// 按键排布位移
#define STEP_POSITION_POINT(_start_x, _start_y, _gap, _step) POSITION_X(_start_x, _gap, _step), POSITION_Y(_start_y, _gap, _step)

// 界面切换按钮设置
#define WIDGET_SWITCH_SETTING(_button, _cur_step) do { \
	_button->move(STEP_POSITION_POINT(widgetSwitchButton_start_x, widgetSwitchButton_start_y, widgetSwitchButton_gap, _cur_step)); \
	_button->setFixedSize(widgetSwitchButton_size_x * WIDGET_ZOOM, widgetSwitchButton_size_y * WIDGET_ZOOM); \
	_button->setBackgroundImage(GET_STRING_FROM_JSON(_global_config, "settings", "push_button_path")); \
	_button->setImageScaleMode(Qt::IgnoreAspectRatio); \
	_button->setFont(BlueakaFontLoader::instance()->createFont(11 * WIDGET_ZOOM)); \
	_button->setBorderWidth(4); \
	_button->setStyleSheet("color: rgb(44, 69, 99);"); \
} while (0)

// 界面内设置控件设置-描述文本
#define WIDGET_CHILD_SETTING_LABEL(_label, _text, _cur_step) do { \
	_label->move(STEP_POSITION_POINT(230, 20, 40, _cur_step)); \
	_label->resize(140 * WIDGET_ZOOM, 24 * WIDGET_ZOOM); \
	_label->setFont(BlueakaFontLoader::instance()->createFont(11 * WIDGET_ZOOM)); \
	_label->setText(GET_STRING_FROM_JSON(_global_dict, "settings", _text)); \
	_label->setStyleSheet("color: rgb(44, 69, 99);"); \
} while (0)

// 界面内设置控件设置-输入框
#define WIDGET_CHILD_SETTING_INPUT(_lineEdit, _cur_step) do { \
	_lineEdit->move(STEP_POSITION_POINT(370, 20, 40, _cur_step)); \
	_lineEdit->resize(140 * WIDGET_ZOOM, 24 * WIDGET_ZOOM); \
	_lineEdit->setFont(BlueakaFontLoader::instance()->createFont(11 * WIDGET_ZOOM)); \
	_lineEdit->setStyleSheet( \
			"QLineEdit {" \
			"    background-color: transparent;" \
			"    border: none;" \
			"    border-bottom: 2px solid #e0e0e0;" \
			"    padding: 3px 2px 0px 2px;" \
			"    color: rgb(44, 69, 99);" \
			"}" \
			"QLineEdit:focus {" \
			"    border-bottom: 2px solid #9e9e9e;" \
			"}" \
			"QLineEdit:hover {" \
			"    border-bottom: 2px solid #3498db;" \
			"}" \
	); \
} while (0)

// 界面内设置控件设置-输入框-数字输入
#define WIDGET_CHILD_SETTING_INPUT_NUMBER(_lineEdit, _config_sort, _cur_data, _cur_step) do { \
	WIDGET_CHILD_SETTING_INPUT(_lineEdit, _cur_step); \
	_lineEdit->setText(QString::number(GET_INT_FROM_JSON(_global_config, _config_sort, _cur_data))); \
} while (0)

// 界面内设置控件设置-输入框-字符串输入
#define WIDGET_CHILD_SETTING_INPUT_STRING(_lineEdit, _config_sort, _cur_data, _cur_step) do { \
	WIDGET_CHILD_SETTING_INPUT(_lineEdit, _cur_step); \
	_lineEdit->setText(GET_STRING_FROM_JSON(_global_config, _config_sort, _cur_data)); \
} while (0)

class SettingsWidget : public QWidget
{
	Q_OBJECT

public:
	SettingsWidget(QWidget *parent = nullptr);
	~SettingsWidget();

protected:
	void closeEvent(QCloseEvent* event) override;
	void mousePressEvent(QMouseEvent* event) override;
	void mouseMoveEvent(QMouseEvent* event) override;
	void mouseReleaseEvent(QMouseEvent* event) override;
	
private slots:
	void onCloseButtonClicked();           // CloseButton被按了
	void onBasicSettingsButtonClicked();     // 基础设置按钮被按了
	void onAronaLMSettingsButtonClicked();     // AronaLM设置按钮被按了
	void onSpineSettingsButtonClicked();     // Spine设置按钮被按了
	void onGptSOVITSSettingsButtonClicked();     // GPT-SOVITS设置按钮被按了
	void onDebugOutputButtonClicked();     // 调试输出按钮被按了
	void onAboutDeveloperButtonClicked();     // 关于开发者按钮被按了
	void onAronaAIModeSwitchButtonClicked();	// 运行模式切换按钮被按了
	void receiveDebugMessage(const QString& message);	// 接收到调试信息

private:
	// 界面切换按钮实现函数

	Ui::SettingsWidgetClass ui;

	// 界面切换按钮
	int widgetSwitchButton_start_x = 115;	// 最上方的控件x坐标
	int widgetSwitchButton_start_y = 40;	// 最上方的控件y坐标
	int widgetSwitchButton_gap = 40;	// y坐标高度差
	int widgetSwitchButton_size_x = 160;	// 按钮x尺寸
	int widgetSwitchButton_size_y = 30;	// 按钮y尺寸

	// 鼠标拖动
	QPointF m_dragPosition;  // 记录拖动起始位置
	bool m_isDragging;       // 是否正在拖动
};

