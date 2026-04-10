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
  await new Promise<void>((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      client.removeListener('sync' as any, onSync)
      resolve() // resolve anyway after 5s — room data may or may not be ready
    }, 5000)

    const onSync = (state: string) => {
      if (state === 'PREPARED' || state === 'ERROR' || state === 'STOPPED') {
        clearTimeout(timeoutId)
        client.removeListener('sync' as any, onSync)
        resolve()
      }
    }

    // Check if already synced
    const currentState = client.getSyncState()
    if (currentState === 'PREPARED') {
      clearTimeout(timeoutId)
      resolve()
      return
    }

    client.on('sync' as any, onSync)
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
