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


#include <SystemTray.h>
#include "SettingsWidget.h"
#include "MainController.h"
#include <QSignalBlocker>

SystemTray::SystemTray(MainWidget* mainWidget, MainController* mainController)
    : m_mainWidget(mainWidget)
	, m_mainController(mainController)
	, m_settingsWidget(nullptr)
{
    // 检查系统是否支持托盘图标
    if (!QSystemTrayIcon::isSystemTrayAvailable()) {
        QMessageBox::critical(nullptr, GET_STRING_FROM_JSON(_global_dict, "application_data", "system_tray"), GET_STRING_FROM_JSON(_global_dict, "application_data", "system_tray_not_support"));
        // 可以选择退出或继续但不显示托盘
        return;
    }

    // 创建动作 (Actions)
    m_operateMainWidget_showOrHide = new QAction(GET_STRING_FROM_JSON(_global_dict, "application_data", "showOrHide_main_widget"));
    m_operateSettingsWidget_showOrHide = new QAction(GET_STRING_FROM_JSON(_global_dict, "application_data", "showOrHide_settings_widget"));
    m_ableEdit = new QAction(GET_STRING_FROM_JSON(_global_dict, "application_data", "able_edit"));
    m_unableEdit = new QAction(GET_STRING_FROM_JSON(_global_dict, "application_data", "unable_edit"));
    m_imageInput = new QAction(GET_STRING_FROM_JSON(_global_dict, "application_data", "image_input_toggle"));
    m_imageInput->setCheckable(true);
    m_quitAction = new QAction(GET_STRING_FROM_JSON(_global_dict, "application_data", "quit"));

    // 连接动作的信号到对应的槽函数
    connect(m_operateMainWidget_showOrHide, &QAction::triggered, this, &SystemTray::showOrHideMainWidget);
    connect(m_operateSettingsWidget_showOrHide, &QAction::triggered, this, &SystemTray::showOrHideSettingsWidget);
    connect(m_ableEdit, &QAction::triggered, this, &SystemTray::ableEdit);
    connect(m_unableEdit, &QAction::triggered, this, &SystemTray::unableEdit);
    connect(m_quitAction, &QAction::triggered, qApp, &QApplication::quit);
    if (m_mainController) {
        m_imageInput->setChecked(m_mainController->isImageInputEnabled());
        connect(m_imageInput, &QAction::toggled, m_mainController, &MainController::setImageInputEnabled);
        connect(m_mainController, &MainController::imageInputChanged, this, [this](bool enabled) {
            if (!m_imageInput) {
                return;
            }
            const QSignalBlocker blocker(m_imageInput);
            m_imageInput->setChecked(enabled);
        });
    }

    // 创建托盘图标和菜单
    m_trayIconMenu = new QMenu();
    m_trayIconMenu->addAction(m_operateMainWidget_showOrHide);
    m_trayIconMenu->addAction(m_operateSettingsWidget_showOrHide);
    m_trayIconMenu->addAction(m_ableEdit);
    m_trayIconMenu->addAction(m_unableEdit);
    m_trayIconMenu->addAction(m_imageInput);
    m_trayIconMenu->addSeparator(); // 添加分隔线
    m_trayIconMenu->addAction(m_quitAction);

    // 创建托盘图标
    m_trayIcon = new QSystemTrayIcon(this);
    m_trayIcon->setIcon(QIcon(GET_STRING_FROM_JSON(_global_config, "settings", "icon_path")));  // 请替换为你的图标资源路径
    m_trayIcon->setToolTip(GET_STRING_FROM_JSON(_global_dict, "application_data", "application_name")); // 鼠标悬停时的提示

    // 将菜单设置给托盘图标（右键菜单）
    m_trayIcon->setContextMenu(m_trayIconMenu);

    // 最后，显示托盘图标
    m_trayIcon->show();

}

SystemTray::~SystemTray()
{
	delete m_settingsWidget;
	m_settingsWidget = nullptr;
}

void SystemTray::ensureSettingsWidget()
{
	if (m_settingsWidget) {
		return;
	}
	m_settingsWidget = new SettingsWidget;
	FINE_DEBUG_OUTPUT("[Qt Operation]SettingsWidget created on first open");
}

void SystemTray::showOrHideMainWidget()
{
    if (m_mainWidget->isVisible()) m_mainWidget->hide();
    else m_mainWidget->show();
}

void SystemTray::showOrHideSettingsWidget()
{
	ensureSettingsWidget();
	if (m_settingsWidget->isVisible()) m_settingsWidget->hide();
    else m_settingsWidget->show();
}

void SystemTray::showSettingsWidget()
{
	ensureSettingsWidget();
	m_settingsWidget->show();
}

void SystemTray::ableEdit()
{
    m_mainWidget->setMouseTransparent(false);
}

void SystemTray::unableEdit()
{
    m_mainWidget->setMouseTransparent(true);
}
