from channels.generic.websocket import AsyncJsonWebsocketConsumer


class AuctionConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.item_id = self.scope['url_route']['kwargs'].get('item_id')
        if not self.item_id:
            await self.close()
            return
        self.group_name = f"auction_{self.item_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # No incoming messages expected; ignore
        pass

    async def new_bid(self, event):
        # Forward bid event to client
        await self.send_json({
            'type': 'new_bid',
            'bid': event.get('bid', {}),
        })
