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

function uuidv4(): string {
  // crypto.randomUUID() requires a secure context (HTTPS/localhost).
  // Use a portable UUID v4 implementation so this works over plain HTTP too.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export function generateTraceId(): string {
  return uuidv4()
}

export async function sendQuery(
  client: MatrixClient,
  roomId: string,
  question: string,
  rolesJwt: string
): Promise<string> {
  const traceId = generateTraceId()
  // Exchange the roles JWT for a short ticket that rides the message body.
  // The AgentTeams runtime's message mapper forwards only content.body to
  // the manager agent — custom fields like x-hb-auth are dropped, so the
  // cryptographic identity must travel as a body marker that the dispatch
  // scripts extract and pass to the MCP layer for verification.
  let body = question
  const ticket = rolesJwt ? await exchangeTicket(rolesJwt) : null
  if (ticket) {
    body = `${question}\n\n[ticket: ${ticket}]`
  }
  // @ts-ignore — sendEvent accepts string event types at runtime
  await client.sendEvent(roomId, 'm.room.message' as sdk.EventType, {
    msgtype: 'm.text',
    body,
    'x-honeybadge': {
      v: '1',
      contract: '001',
      trace_id: traceId,
      payload: { question },
    },
    // Kept for protocol compatibility (used if the runtime ever forwards
    // custom fields); the ticket above is the operative identity carrier.
    'x-hb-auth': rolesJwt,
  })
  return traceId
}

/**
 * Exchange the roles JWT for a short-lived auth ticket via honeybadge-server.
 * Returns null on any failure — the caller falls back to a ticketless body
 * (queries then fail closed at the MCP layer when REQUIRE_AUTH is on).
 */
export async function exchangeTicket(rolesJwt: string): Promise<string | null> {
  try {
    const resp = await fetch('/api/auth/ticket', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${rolesJwt}`,
        'Content-Type': 'application/json',
      },
    })
    if (!resp.ok) return null
    const envelope = await resp.json()
    const ticket = envelope?.data?.ticket
    return typeof ticket === 'string' && ticket.length > 0 ? ticket : null
  } catch {
    return null
  }
}

/** Strip the trailing "[ticket: ...]" marker from a message body. */
export function stripTicketMarker(body: string): string {
  return body.replace(/\s*\[ticket:\s*[^\]]*\]\s*$/, '')
}
