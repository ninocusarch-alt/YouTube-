import os
import tempfile
from pathlib import Path


API_KEY_NAME = 'DASHSCOPE_API_KEY'
MAX_API_KEY_LENGTH = 4096


class ConfigStore:
    def __init__(self, env_file: Path, template_file: Path) -> None:
        self.env_file = env_file.resolve()
        self.template_file = template_file.resolve()

    def ensure_exists(self) -> None:
        if self.env_file.exists():
            return
        if not self.template_file.exists():
            raise FileNotFoundError(f'配置模板不存在：{self.template_file}')
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.template_file.read_text(encoding='utf-8'))

    def read_value(self, name: str) -> str:
        if not self.env_file.exists():
            return ''
        prefix = f'{name}='
        for raw_line in self.env_file.read_text(encoding='utf-8-sig').splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#') or not line.startswith(prefix):
                continue
            return line[len(prefix):].strip().strip('"\'')
        return ''

    def is_configured(self) -> bool:
        return bool(self.read_value(API_KEY_NAME))

    def save_api_key(self, api_key: str) -> None:
        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError('API Key 不能为空。')
        if '\n' in cleaned or '\r' in cleaned:
            raise ValueError('API Key 不能包含换行。')
        if len(cleaned) > MAX_API_KEY_LENGTH:
            raise ValueError(f'API Key 不能超过 {MAX_API_KEY_LENGTH} 个字符。')
        if any(character.isspace() for character in cleaned):
            raise ValueError('API Key 中间不能包含空格，请重新完整复制。')

        self.ensure_exists()
        lines = self.env_file.read_text(encoding='utf-8-sig').splitlines()
        prefix = f'{API_KEY_NAME}='
        updated = False
        output: list[str] = []
        for line in lines:
            if line.strip().startswith(prefix):
                output.append(f'{prefix}{cleaned}')
                updated = True
            else:
                output.append(line)
        if not updated:
            output.append(f'{prefix}{cleaned}')
        self._atomic_write('\n'.join(output).rstrip() + '\n')

    def masked_api_key(self) -> str:
        value = self.read_value(API_KEY_NAME)
        if not value:
            return '未配置'
        if len(value) <= 8:
            return '*' * len(value)
        return f'{value[:4]}{"*" * max(4, len(value) - 8)}{value[-4:]}'

    def _atomic_write(self, content: str) -> None:
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                newline='\n',
                dir=self.env_file.parent,
                prefix=f'.{self.env_file.name}.',
                suffix='.tmp',
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temp_path = Path(temporary.name)
            os.replace(temp_path, self.env_file)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
