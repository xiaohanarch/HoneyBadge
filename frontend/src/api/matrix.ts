import * as sdk from 'matrix-js-sdk'

export type MatrixClient = sdk.MatrixClient

export function createMatrixClient(
  homeserver: string,
  accessToken: string,
  userId: string
): MatrixClient {
  return sdk.createClient({
    baseUrl: homeserver,
    accessToken,
    userId,
  })
}

export async function findOrCreateManagerDmRoom(
  client: MatrixClient,
  managerUserId: string
): Promise<string> {
  await client.startClient({ initialSyncLimit: 10 })

  // Wait for initial sync
  await new Promise<void>((resolve) => {
    const checkSync = () => {
      if (client.getSyncState() === 'PREPARED' || client.getSyncState() === 'SYNCING') {
        resolve()
      } else {
        setTimeout(checkSync, 200)
      }
    }
    checkSync()
  })

  // Look in existing direct rooms
  // @ts-ignore — 'm.direct' is a valid account data key at runtime
  const directRooms = client.getAccountData('m.direct')
  if (directRooms) {
    const dmMap = directRooms.getContent() as Record<string, string[]>
    const rooms = dmMap[managerUserId]
    if (rooms && rooms.length > 0) {
      return rooms[0]
    }
  }

  // Create new DM room with manager
  const resp = await client.createRoom({
    is_direct: true,
    invite: [managerUserId],
    preset: 'private_chat' as sdk.Preset,
  })
  return resp.room_id
}

export function generateTraceId(): string {
  return crypto.randomUUID()
}

export async function sendQuery(
  client: MatrixClient,
  roomId: string,
  question: string,
  rolesJwt: string
): Promise<string> {
  const traceId = generateTraceId()
  // @ts-ignore — sendEvent accepts string event types at runtime
  await client.sendEvent(roomId, 'm.room.message' as sdk.EventType, {
    msgtype: 'm.text',
    body: question,
    'x-honeybadge': {
      v: '1',
      contract: '001',
      trace_id: traceId,
      payload: { question },
    },
    'x-hb-auth': rolesJwt,
  })
  return traceId
}
