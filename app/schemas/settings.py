from pydantic import BaseModel

class SettingsBase(BaseModel):
    delay: bool = False
    min_delay_seconds: int = 1
    max_delay_seconds: int = 5
    sleep: bool = False
    sleep_after_messages: int = 1
    min_sleep_seconds: int = 1
    max_sleep_seconds: int = 5

class SettingsRead(SettingsBase):
    pass
    
class SettingsUpdate(SettingsBase):
    pass