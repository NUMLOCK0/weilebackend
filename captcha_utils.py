import random
import string
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def generate_captcha(length=4, width=120, height=40):
    """
    生成图形验证码，返回 (验证码文本, Base64 图片字符串)
    """
    # 生成随机验证码文本 (大写字母和数字，排除容易混淆的字符)
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = ''.join(random.choice(chars) for _ in range(length))
    
    # 创建图片
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # 填充背景噪点
    for _ in range(100):
        xy = (random.randint(0, width), random.randint(0, height))
        draw.point(xy, fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    
    # 画干扰线
    for _ in range(5):
        start = (random.randint(0, width), random.randint(0, height))
        end = (random.randint(0, width), random.randint(0, height))
        draw.line([start, end], fill=(random.randint(0, 150), random.randint(0, 150), random.randint(0, 150)), width=1)

    # 绘制文字
    # 尝试加载内置或系统字体，如果失败则使用默认字体
    try:
        # Windows 常用字体路径示例，或者你可以指定具体的 ttf 文件
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        font = ImageFont.load_default()

    for i, char in enumerate(code):
        # 随机旋转文字ImageFilter3
        char_img = Image.new('RGBA', (30, 30), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_img)
        char_draw.text((0, 0), char, font=font, fill=(random.randint(0, 150), 0, 0))
        rotated_char = char_img.rotate(random.randint(-30, 30), expand=1)
        # 粘贴到主图
        img.paste(rotated_char, (10 + i * 25, 5), rotated_char)

    # 模糊处理
    img = img.filter(ImageFilter.SMOOTH)
    
    # 转为 Base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return code, f"data:image/png;base64,{img_str}"
