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
