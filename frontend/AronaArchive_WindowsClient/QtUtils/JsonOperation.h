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

#ifndef JSONOPERATION_H
#define JSONOPERATION_H

#include <Defines.h>

#include <QFile>          // 文件操作
#include <QJsonDocument>  // JSON文档
#include <QJsonObject>    // JSON对象
#include <QJsonParseError> // 错误处理
#include <QJsonValue>
#include <QDebug>         // 调试输出

class JsonOperation {
public:
	// 构造函数
	// 无参数构造
	JsonOperation();
	// 传入文件路径
	JsonOperation(QString file_path);
	// 直接传入Json对象
	JsonOperation(const QJsonObject& jsonObj);
	
	// 析构函数
	~JsonOperation();

	// 通过key，获取该Json文件中对应的value值
	QVariant getValue(QString key);

	// 直接获取QString类型数据
	QString getString(QString key);

	// 直接获取int类型数据
	int getInt(QString key);

	// 直接获取double类型数据
	double getDouble(QString key);

	// 直接获取bool类型数据
	bool getBool(QString key);

	// 直接获取Json类型数据
	JsonOperation getJson(QString key);

	QVariant static analysisJson(QString json, QString key);

	// 设置/修改值（通用方法）
	void setValue(QString key, const QVariant& value);

	// 设置字符串值
	void setString(QString key, const QString& value);

	// 设置整数值
	void setInt(QString key, int value);

	// 设置双精度浮点数值
	void setDouble(QString key, double value);

	// 设置布尔值
	void setBool(QString key, bool value);

	// 设置JSON对象值
	void setJson(QString key, const JsonOperation& jsonObj);
	void setJsonObject(QString key, const QJsonObject& jsonObj);

	// 链式修改Json->Json->值
	bool setIntInJson(QString jsonKey, QString valueKey, int value);
	bool setDoubleInJson(QString jsonKey, QString valueKey, double value);
	bool setStringInJson(QString jsonKey, QString valueKey, QString value);
	bool setBoolInJson(QString jsonKey, QString valueKey, bool value);

	// 写回构造时打开的 JSON 文件（内存构造则失败）
	bool save() const;

	// JSON对象引用
	QJsonObject m_jsonObj;

private:
	QString m_filePath;

};

#endif // JSONOPERATION_H