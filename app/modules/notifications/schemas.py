from datetime import datetime
from app.core.schemas import StrictModel
class NotificationOut(StrictModel):
    id:int;user_id:int;title:str;message:str;is_read:bool;created_at:datetime
class NotificationPage(StrictModel):
    items:list[NotificationOut];total:int;page:int;limit:int;pages:int
class ReadAllOut(StrictModel):ok:bool
