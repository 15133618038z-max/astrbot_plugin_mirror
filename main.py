import os
import asyncio
import time
import aiohttp
from PIL import Image as PILImage
from astrbot.api.all import *
from astrbot.api.event import filter


@register(
    "mirror",
    "kaf",
    "图片对称镜像反转插件",
    "1.0.0",
    "https://github.com/15133618038z-max/astrbot_plugin_mirror"
)
class MirrorPlugin(Star):
    """图片对称镜像反转插件"""
    
    def __init__(self, context: Context):
        super().__init__(context)
        self._temp_dir = os.path.join(os.getcwd(), "data", "mirror_temp")
        os.makedirs(self._temp_dir, exist_ok=True)
        asyncio.create_task(self._cleanup_old_files())

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        """监听所有消息，匹配 反转 触发"""
        start_time = time.time()
        
        # 快速过滤：消息文本不包含 反转 直接返回
        msg = event.message_str.strip()
        if "反转" not in msg:
            return
        
        # 严格匹配：消息必须是 反转 或以 反转 开头
        if msg != "反转" and not msg.startswith("反转 "):
            return

        logger.info(f"[反转] 触发指令，耗时: {time.time() - start_time:.3f}s")

        try:
            # 提取图片
            extract_start = time.time()
            image_urls = await self._extract_image_urls(event)
            logger.info(f"[反转] 提取图片完成，耗时: {time.time() - extract_start:.3f}s，找到 {len(image_urls)} 张")
            
            if not image_urls:
                yield event.plain_result("未检测到图片，请引用图片或直接发送图片后使用 反转")
                return

            if len(image_urls) > 3:
                image_urls = image_urls[:3]

            # 处理图片
            results = []
            for idx, img_url in enumerate(image_urls, 1):
                try:
                    process_start = time.time()
                    output_path = await self._process_image(img_url, idx)
                    if output_path:
                        results.append(output_path)
                        logger.info(f"[反转] 图片 {idx} 处理完成，耗时: {time.time() - process_start:.3f}s")
                except Exception as e:
                    logger.error(f"[反转] 处理第 {idx} 张图片失败: {e}")
                    continue

            if not results:
                yield event.plain_result("所有图片处理失败")
                return

            # 发送图片
            for output_path in results:
                yield event.image_result(output_path)
            
            logger.info(f"[反转] 总耗时: {time.time() - start_time:.3f}s")
            
            # 延迟删除
            asyncio.create_task(self._delayed_delete(results, delay=30))

        except Exception as e:
            logger.error(f"[反转] 执行失败: {e}")
            yield event.plain_result(f"处理失败: {str(e)}")

    async def _extract_image_urls(self, event: AstrMessageEvent) -> list:
        """提取图片 URL（优先直接图片，无图片时才查引用）"""
        image_urls = []
        message_chain = event.get_messages()

        # 方式 1：消息中直接带图
        for comp in message_chain:
            if isinstance(comp, Image):
                url = comp.url or comp.file
                if url:
                    image_urls.append(url)

        # 如果已经有图片，直接返回，不查引用消息
        if image_urls:
            return image_urls

        # 方式 2：引用消息中的图（只在没有直接图片时才执行）
        for comp in message_chain:
            if isinstance(comp, Reply):
                try:
                    if hasattr(event, 'bot'):
                        # 添加超时控制
                        ref_msg = await asyncio.wait_for(
                            event.bot.get_msg(message_id=int(comp.id)),
                            timeout=5.0
                        )
                        for seg in ref_msg.get("message", []):
                            if seg.get("type") == "image":
                                url = seg.get("data", {}).get("url") or seg.get("data", {}).get("file")
                                if url:
                                    image_urls.append(url)
                except asyncio.TimeoutError:
                    logger.warning(f"[反转] 获取引用消息超时")
                except Exception as e:
                    logger.warning(f"[反转] 获取引用消息失败: {e}")

        return image_urls

    async def _process_image(self, img_url: str, idx: int) -> str:
        """下载、反转、保存图片"""
        tmp_input = None
        tmp_output = None

        try:
            # 下载图片
            if img_url.startswith("http"):
                tmp_input = os.path.join(self._temp_dir, f"input_{int(time.time()*1000)}_{idx}.tmp")
                async with aiohttp.ClientSession() as session:
                    async with session.get(img_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            raise Exception(f"下载失败，HTTP {resp.status}")
                        data = await resp.read()
                with open(tmp_input, "wb") as f:
                    f.write(data)
            elif img_url.startswith("file:///"):
                tmp_input = img_url.replace("file:///", "")
                if not os.path.exists(tmp_input):
                    raise Exception(f"本地文件不存在: {tmp_input}")
            else:
                tmp_input = img_url
                if not os.path.exists(tmp_input):
                    raise Exception(f"文件路径无效: {tmp_input}")

            # 打开图片（GIF 自动取首帧）
            img = PILImage.open(tmp_input).convert("RGB")
            w, h = img.size

            # 对称反转：左半保留 + 右半镜像
            left_half = img.crop((0, 0, w // 2, h))
            mirrored = left_half.transpose(PILImage.FLIP_LEFT_RIGHT)
            result = PILImage.new("RGB", (w, h))
            result.paste(left_half, (0, 0))
            result.paste(mirrored, (w // 2, 0))

            tmp_output = os.path.join(self._temp_dir, f"output_{int(time.time()*1000)}_{idx}.jpg")
            result.save(tmp_output, "JPEG", quality=80)

            return tmp_output

        finally:
            if tmp_input and img_url.startswith("http") and os.path.exists(tmp_input):
                try:
                    os.remove(tmp_input)
                except Exception:
                    pass

    async def _delayed_delete(self, file_paths: list, delay: int = 30):
        """延迟删除文件"""
        await asyncio.sleep(delay)
        for path in file_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                logger.warning(f"[反转] 删除文件失败: {e}")

    async def _cleanup_old_files(self):
        """定期清理超过 1 小时的旧文件"""
        while True:
            try:
                await asyncio.sleep(3600)
                now = time.time()
                cleaned = 0
                for filename in os.listdir(self._temp_dir):
                    filepath = os.path.join(self._temp_dir, filename)
                    if os.path.isfile(filepath) and now - os.path.getmtime(filepath) > 3600:
                        try:
                            os.remove(filepath)
                            cleaned += 1
                        except Exception:
                            pass
                if cleaned > 0:
                    logger.info(f"[反转] 清理了 {cleaned} 个旧文件")
            except Exception as e:
                logger.error(f"[反转] 定期清理任务出错: {e}")
