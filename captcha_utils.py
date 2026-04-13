import random
import base64
from io import BytesIO
from captcha.image import ImageCaptcha

def generate_captcha(length=4, width=160, height=60):
    """
    使用 captcha 库生成图形验证码，返回 (验证码文本, Base64 图片字符串)
    """
    # 生成随机验证码文本 (大写字母和数字，排除容易混淆的字符)
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = ''.join(random.choice(chars) for _ in range(length))
    
    # 使用 ImageCaptcha 库生成图片
    # 可以通过 fonts 参数指定字体列表，如果不指定则使用库自带的
    generator = ImageCaptcha(width=width, height=height)
    
    # 生成图片数据
    img_data = generator.generate(code)
    
    # 转为 Base64
    img_base64 = base64.b64encode(img_data.getvalue()).decode()
    
    return code, f"data:image/png;base64,{img_base64}"
