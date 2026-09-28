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

#include <Defines.h>
#include <GlobalVariables.h>
#include "MainController.h"

#include <QObject>
#include <QHotKey>
#include <QKeySequence>
#include <QApplication>

class ShortCutKey  : public QObject
{
	Q_OBJECT

public:
	ShortCutKey(MainController* mainController);
	~ShortCutKey();

private slots:
	void onSwitchAudioInput();
	void onSwitchMouseTransparent();
	void onShowUserInput();
	void onSwitchImageInput();
	void onCancelComputerUse();

private:
	MainController* m_mainController = nullptr;
	QHotkey* m_switchAudioInput = nullptr;
	QHotkey* m_switchMouseTransparent = nullptr;
	QHotkey* m_showUserInput = nullptr;
	QHotkey* m_switchImageInput = nullptr;
	QHotkey* m_cancelComputerUse = nullptr;
	bool m_switchAudioInputEnabled = false;

};
