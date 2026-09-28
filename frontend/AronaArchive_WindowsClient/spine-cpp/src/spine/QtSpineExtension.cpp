#include <spine/QtSpineExtension.h>

// 构造函数空实现
QtSpineExtension::QtSpineExtension() : spine::SpineExtension() {
}

// 虚析构函数空实现
QtSpineExtension::~QtSpineExtension() {
}

void* QtSpineExtension::_alloc(size_t size, const char* file, int line)
{
	// 分配一块size那么大的内存
	void* mem = std::malloc(size);	
	// 调试信息
	//qDebug() << "[Spine Operation] Allocating memory: " << size << " bytes at " << file << ":line " << line;
	// 返回分配的内存地址
	return mem;	
}

void* QtSpineExtension::_calloc(size_t size, const char* file, int line)
{
	// 分配一块size那么大的内存，并初始化为0
	void* mem = std::calloc(1, size);
	// 调试信息
	//qDebug() << "[Spine Operation] Allocating zero-initialized memory: " << size << " bytes at " << file << ":line " << line;
	// 返回分配的内存地址
	return mem;
}

void* QtSpineExtension::_realloc(void* ptr, size_t size, const char* file, int line)
{
	// 重新分配内存块ptr为size大小
	void* mem = std::realloc(ptr, size);
	// 调试信息
	//qDebug() << "[Spine Operation] Reallocating memory: " << size << " bytes at " << file << ":line " << line;
	// 返回重新分配的内存地址
	return mem;
}

void QtSpineExtension::_free(void* mem, const char* file, int line)
{
	if (mem) {
		// 释放内存块mem
		std::free(mem);
		// 调试信息
		//qDebug() << "[Spine Operation] Freeing memory at " << file << ":line " << line;
	}
}

char* QtSpineExtension::_readFile(const spine::String& path, int* length)
{
	// 初始化输出参数，读取失败时置0
	*length = 0;
	// 将spine路径转换为QString
	QString qPath = QString::fromStdString(path.buffer());
	QFile file(qPath);
	// 以只读二进制打开文件（不可使用 QIODevice::Text：Windows 会剥掉 0x0D，破坏 .skel）
	if (!file.open(QIODevice::ReadOnly | QIODevice::Unbuffered)) {
		// 打开失败，输出日志
		qWarning() << "[Spine Operation] Open File Failed! Path: " << qPath << " | Reason: " << file.errorString();
		return nullptr;
	}
	// 读取所有文件到Qt字节数组(QByteArray)
	QByteArray byteData = file.readAll();
	// 关闭文件
	file.close();
	// 读取失败判断
	if (byteData.isEmpty()) {
		qWarning() << "[Spine Operation] File is Empty! Path: " << qPath;
		return nullptr;
	}
	// 给上层返回文件数据
	*length = byteData.size();
	char* data = static_cast<char*>(_alloc(*length + 1, __FILE__, __LINE__));
	std::memcpy(data, byteData.constData(), *length);
	data[*length] = '\0';	// 末尾加\0，支持C字符串解析
	//qDebug() << "[Spine Opperation] Read File Success! Path: " << qPath << " | Length: " << *length;
	// 返回文件数据指针
	return data;
}

// 局部静态扩展实例
static QtSpineExtension g_QtSpineExtension;

// 实现全局扩展实例的函数
spine::SpineExtension* spine::getDefaultExtension() {
	return &g_QtSpineExtension;
}