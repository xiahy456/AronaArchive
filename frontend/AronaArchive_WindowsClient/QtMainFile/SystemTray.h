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

#ifndef SYSTEMTRAY_H
#define SYSTEMTRAY_H

#include <QObject>
#include <QSystemTrayIcon>
#include <QMenu>
#include <QAction>
#include <QCloseEvent>
#include <QApplication>
#include <QMessageBox>

#include "MainWidget.h"

#include "GlobalInclude.h"

class MainController;

class SystemTray : public QObject 
{
	Q_OBJECT

public:
	// 构造函数
	SystemTray(MainWidget* mainWidget, MainController* mainController = nullptr);
	// 析构函数
	~SystemTray();

	// 显示主窗口
	void showOrHideMainWidget();
	// 显示/隐藏设置窗口（首次打开时创建设置界面）
	void showOrHideSettingsWidget();
	// 显示设置窗口（首次打开时创建）
	void showSettingsWidget();
	// 允许操作主菜单
	void ableEdit();
	// 禁止操作主菜单
	void unableEdit();

private:
	void ensureSettingsWidget();

	MainWidget* m_mainWidget;	// mainWidget主界面对象的引用
	MainController* m_mainController = nullptr;
	QWidget* m_settingsWidget = nullptr;	// settingsWidget设置界面（首次打开时创建）
	QSystemTrayIcon* m_trayIcon = nullptr;	// 系统托盘图标对象
	QMenu* m_trayIconMenu = nullptr;	// 托盘图标关联的菜单

	QAction* m_operateMainWidget_showOrHide = nullptr;	// 显示/隐藏主界面
	QAction* m_operateSettingsWidget_showOrHide = nullptr;	// 显示/隐藏设置界面
	QAction* m_ableEdit = nullptr;	// 可操作主菜单
	QAction* m_unableEdit = nullptr;	// 不可操作主菜单
	QAction* m_imageInput = nullptr;	// 启用图片输入
	QAction* m_quitAction = nullptr;	// 退出程序
};

#endif // !SYSTEMTRAY_H
