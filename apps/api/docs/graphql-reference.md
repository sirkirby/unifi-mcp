# unifi-api-server GraphQL Reference

> Auto-generated from the Strawberry schema by `unifi_api.graphql.docgen`.
> Regenerate with `python -m unifi_api.graphql.docgen`.


## Schema (full SDL)


```graphql

"""A UniFi Access device (reader / hub / lock)."""
type AccessDevice {
  id: ID
  name: String
  type: String
  isOnline: Boolean
  firmwareVersion: String
  mac: String
  ip: String
  location: AccessLocation
}

"""
A single per-device config/settings entry (key/value with category tag).
"""
type AccessDeviceConfig {
  deviceId: ID
  key: String
  value: String
  tag: String
  updateTime: String
  createTime: String
}

"""A device's config/settings entries."""
type AccessDeviceConfigPage {
  items: [AccessDeviceConfig!]!
  nextCursor: String
}

"""Paginated page of UniFi Access devices."""
type AccessDevicePage {
  items: [AccessDevice!]!
  nextCursor: String
}

"""A UniFi Access event row (list + detail share this shape)."""
type AccessEvent {
  id: ID
  type: String
  timestamp: String
  doorId: String
  userId: String
  credentialId: String
  message: String
  result: String

  """The door this event references."""
  door: Door

  """The user this event references."""
  user: User
}

"""Paginated page of UniFi Access events."""
type AccessEventPage {
  items: [AccessEvent!]!
  nextCursor: String
}

"""UniFi Access health probe summary."""
type AccessHealth {
  status: String!
  numDoors: Int
  numDevices: Int
  numOfflineDevices: Int
}

"""
Structured location reference (door / floor / building) for an Access device.
"""
type AccessLocation {
  uniqueId: ID
  name: String
  upId: ID
  locationType: String
  fullName: String
  level: Int
}

"""Read-only access to UniFi Access resources."""
type AccessQuery {
  """List doors on the Access controller (paginated)."""
  doors(controller: ID!, limit: Int! = 50, cursor: String = null): DoorPage!

  """Look up a single Access door by id."""
  door(controller: ID!, id: ID!): Door

  """List Access door groups (paginated)."""
  doorGroups(controller: ID!, limit: Int! = 50, cursor: String = null): DoorGroupPage!

  """Get the live status (lock state + last event) of a door."""
  doorStatus(controller: ID!, id: ID!): DoorStatus

  """List Access devices (readers / hubs / locks, paginated)."""
  devices(controller: ID!, limit: Int! = 50, cursor: String = null): AccessDevicePage!

  """Look up a single Access device by id."""
  device(controller: ID!, id: ID!): AccessDevice

  """
  List a device's config/settings entries (e.g. reader voice greeting). Secrets redacted.
  """
  deviceConfigs(controller: ID!, deviceId: ID!): AccessDeviceConfigPage!

  """List Access users (employees / cardholders, paginated)."""
  users(controller: ID!, limit: Int! = 50, cursor: String = null): UserPage!

  """List Access credentials (NFC / PIN / etc., paginated)."""
  credentials(controller: ID!, limit: Int! = 50, cursor: String = null): CredentialPage!

  """Look up a single Access credential by id."""
  credential(controller: ID!, id: ID!): Credential

  """List Access policies (who-can-access-what bindings)."""
  policies(controller: ID!, limit: Int! = 50, cursor: String = null): PolicyPage!

  """Look up a single Access policy by id."""
  policy(controller: ID!, id: ID!): Policy

  """List Access schedules (weekly access windows)."""
  schedules(controller: ID!, limit: Int! = 50, cursor: String = null): SchedulePage!

  """
  List Access Developer API visitors. Returned UUIDs are scoped to the visitor family and must not be passed to other Access user or credential operations.
  """
  visitors(controller: ID!, limit: Int! = 50, cursor: String = null): VisitorPage!

  """
  Look up one Access Developer API visitor using a UUID returned by the visitor family; IDs from other Access user or credential operations are not accepted.
  """
  visitor(controller: ID!, id: ID!): Visitor

  """
  List Access events by system-log topic, paginated most recent first. Use unlocks for door grants and open/close history, access_denial for refused attempts, ring for doorbells, or updates, critical, admin, and admin_activity.
  """
  events(controller: ID!, limit: Int! = 50, cursor: String = null, topic: String! = "admin"): AccessEventPage!

  """Look up a single Access event by id."""
  event(controller: ID!, id: ID!): AccessEvent

  """Get the access activity histogram summary."""
  activitySummary(controller: ID!, doorId: String = null, days: Int! = 7): ActivitySummary

  """Get the Access application info (name + version + host)."""
  systemInfo(controller: ID!): AccessSystemInfo

  """Get the Access health probe summary."""
  health(controller: ID!): AccessHealth
}

"""UniFi Access application info (name + version + host)."""
type AccessSystemInfo {
  name: String
  version: String
  hostname: String
  uptime: Int
}

"""A MAC ACL rule (V2 /acl-rules entry)."""
type AclRule {
  id: ID
  name: String
  enabled: Boolean!
  action: String
  aclIndex: Int
  networkId: String
  sourceType: String
  destinationType: String
  sourceMacs: [String!]!
  destinationMacs: [String!]!
  sourceNetmask: Int
  destinationNetmask: Int
  sourceMacMask: String
  destinationMacMask: String
}

"""Paginated page of ACL rules."""
type AclRulePage {
  items: [AclRule!]!
  nextCursor: String
}

"""An active kernel routing-table entry on a gateway."""
type ActiveRoute {
  targetSubnet: String
  gateway: String
  interface: String
  distance: Int
  origin: String
  routeType: String
}

"""Paginated page of active kernel routes."""
type ActiveRoutePage {
  items: [ActiveRoute!]!
  nextCursor: String
}

"""Access activity histogram summary."""
type ActivitySummary {
  periodStart: String
  periodEnd: String
  totalEvents: Int
  grantedCount: Int
  deniedCount: Int
  topUsers: JSON
  buckets: JSON
}

"""A controller alarm (V1 /list/alarm entry)."""
type Alarm {
  id: ID
  key: String
  msg: String
  archived: Boolean!
  time: Int
}

"""Triggers, actions and scope schema the Alarm Manager accepts in rules."""
type AlarmCatalog {
  triggers: JSON
  actions: JSON
  scope: JSON
}

"""Paginated page of controller alarms."""
type AlarmPage {
  items: [Alarm!]!
  nextCursor: String
}

"""Wrapper for protect_alarm_list_profiles — {profiles, count}."""
type AlarmProfileList {
  profiles: JSON
  count: Int

  """Whether the result has complete Alarm Manager v2 coverage."""
  complete: Boolean

  """Explains missing v2-only profile fields when complete is false."""
  coverageNotice: String
}

"""A UniFi Protect alarm rule (normalized; includes AI-powered alarms)."""
type AlarmRule {
  id: ID
  title: String
  enabled: Boolean
  triggers: JSON
  actions: JSON
  scope: JSON
  stats: JSON
  createdAt: String
  updatedAt: String
}

"""Wrapper for protect_alarm_list_rules — {rules, count}."""
type AlarmRuleList {
  rules: JSON
  count: Int
}

"""UniFi Protect alarm system arm-state snapshot."""
type AlarmStatus {
  armed: Boolean
  status: String
  activeProfileId: String
  activeProfileName: String
  armedAt: String
  willBeArmedAt: String
  breachDetectedAt: String
  breachEventCount: Int
  profileCount: Int
}

"""A UniFi AP group (collection of AP MAC addresses)."""
type ApGroup {
  id: ID
  name: String
  apCount: Int!
  deviceMacs: [String!]!
  wlanGroupIds: [String!]!
}

"""Paginated page of AP groups."""
type ApGroupPage {
  items: [ApGroup!]!
  nextCursor: String
}

"""Auto-backup schedule + retention settings."""
type AutoBackupSettings {
  enabled: Boolean!
  schedule: String
  maxCount: Int
  autobackupEnabled: Boolean
  autobackupCronExpr: String
  autobackupDays: Int
  autobackupMaxFiles: Int
  autobackupTimezone: String
  autobackupCloudEnabled: Boolean
}

"""A wireless channel allowed by the regulatory domain."""
type AvailableChannel {
  channel: Int
  frequencyMhz: Int
  widthMhz: Int
  allowed: Boolean!
}

"""A controller backup file metadata record."""
type Backup {
  id: ID
  filename: String
  size: Int
  createdAt: Int
}

"""Paginated page of controller backup descriptors."""
type BackupPage {
  items: [Backup!]!
  nextCursor: String
}

"""A signed integer that can exceed GraphQL Int's 32-bit range."""
scalar BigInt

"""A client currently blocked on the UniFi Network controller."""
type BlockedClient {
  mac: ID
  hostname: String
  name: String
  lastSeen: String
  blocked: Boolean!
}

"""Paginated page of blocked clients."""
type BlockedClientPage {
  items: [BlockedClient!]!
  nextCursor: String
}

"""A UniFi Protect camera (list + detail shape)."""
type Camera {
  id: ID
  mac: String
  name: String
  model: String
  type: String
  state: String
  firmwareVersion: String
  isRecording: Boolean
  isMotionDetected: Boolean
  isSmartDetected: Boolean
  host: String
  smartDetectTypes: [String!]
  isPtz: Boolean
  channels: JSON
  irLedMode: String
  hdrMode: String
  micEnabled: Boolean
  micVolume: Int
  statusLightOn: Boolean
  speakerVolume: Int
  motionDetection: Boolean

  """Events generated by this camera."""
  events: [Event!]!

  """Recordings from this camera."""
  recordings: [Recording!]!
}

"""Analytics summary for a Protect camera."""
type CameraAnalytics {
  cameraId: ID
  cameraName: String
  detections: JSON
  smartDetects: JSON
  smartAudioDetects: JSON
  currentlyDetected: JSON
  motionZoneCount: Int!
  smartDetectZoneCount: Int!
  stats: JSON
}

"""
Crossing lines, smart-detect zones and loiter zones of a Protect camera.
"""
type CameraDetectionAreas {
  cameraId: ID
  cameraName: String
  areas: [DetectionArea!]!
  count: Int!
}

"""Paginated page of UniFi Protect cameras."""
type CameraPage {
  items: [Camera!]!
  nextCursor: String
}

"""Stream catalog for a Protect camera (channels + RTSPS URLs)."""
type CameraStreams {
  cameraId: ID
  cameraName: String
  channels: JSON
  rtspsStreams: JSON
}

"""A UniFi Protect chime (paired-camera doorbell ringer)."""
type Chime {
  id: ID
  mac: String
  name: String
  model: String
  type: String
  state: String
  isConnected: Boolean
  firmwareVersion: String
  volume: Int
  repeatTimes: Int
  pairedCameras: [String!]!
  ringSettings: JSON
  availableTracks: JSON
}

"""Paginated page of UniFi Protect chimes."""
type ChimePage {
  items: [Chime!]!
  nextCursor: String
}

"""A client device on the UniFi Network controller."""
type Client {
  mac: ID
  ip: String
  hostname: String
  name: String
  isWired: Boolean
  isGuest: Boolean
  status: String!
  lastSeen: String
  firstSeen: String
  note: String
  usergroupId: String
  sourceApi: String

  """
  Public Integration inventory UUID, not a legacy resource ID. These IDs are scoped to the Integration inventory tool family — do not pass them to legacy resource tools.
  """
  integrationId: ID

  """The AP or switch this client connects through."""
  device: Device
}

"""A network member client group (V2 /network-members-group entry)."""
type ClientGroup {
  id: ID
  name: String
  qosRateMaxDown: Int
  qosRateMaxUp: Int
  members: [String!]!
}

"""Paginated page of network member client groups."""
type ClientGroupPage {
  items: [ClientGroup!]!
  nextCursor: String
}

"""Result of a by-IP client lookup — online presence + last seen."""
type ClientLookup {
  mac: ID
  ip: String
  hostname: String
  name: String
  isOnline: Boolean!
  lastSeen: String
}

"""Paginated page of clients."""
type ClientPage {
  items: [Client!]!
  nextCursor: String
}

"""A client association session entry."""
type ClientSession {
  mac: String
  hostname: String
  ap: String
  ssid: String
  connectedAt: Int
  disconnectedAt: Int
  duration: Int
}

"""Paginated page of client association sessions."""
type ClientSessionPage {
  items: [ClientSession!]!
  nextCursor: String
}

"""Current WiFi parameters for a client."""
type ClientWifiDetails {
  mac: String
  ssid: String
  ap: String
  signal: Int
  txRate: Int
  rxRate: Int
  channel: Int

  """Noise floor in dBm."""
  noise: Int

  """Controller-computed satisfaction score (0-100)."""
  satisfaction: Int

  """Transmit retry count since association."""
  txRetries: BigInt

  """Transmit attempt count since association."""
  wifiTxAttempts: BigInt

  """Number of roams since association."""
  roamCount: Int

  """Radio band identifier (e.g. na, ng)."""
  radio: String

  """BSSID of the AP radio the client is associated to."""
  bssid: String

  """Number of spatial streams."""
  nss: Int

  """Whether the client uses 802.11r fast roaming."""
  is11r: Boolean
}

"""A content-filtering profile (V2 /content-filtering entry)."""
type ContentFilter {
  id: ID
  name: String
  enabled: Boolean!
  profile: String
  appliesTo: JSON!
  blockedCategories: [String!]!
  safeSearch: [String!]!
  clientMacs: [String!]!
  networkIds: [String!]!
  scheduleMode: String
  scheduleDays: [String!]
  scheduleTimeAllDay: Boolean
  scheduleTimeStart: String
  scheduleTimeEnd: String
  scheduleDateStart: String
  scheduleDateEnd: String
}

"""Paginated page of content filters."""
type ContentFilterPage {
  items: [ContentFilter!]!
  nextCursor: String
}

"""A UniFi Access credential (NFC, PIN, etc.)."""
type Credential {
  id: ID
  userId: String
  type: String
  status: String
  expiry: String
  lastUsed: String
  token: String
  pinCode: String
}

"""Paginated page of UniFi Access credentials."""
type CredentialPage {
  items: [Credential!]!
  nextCursor: String
}

type CustomService {
  name: String
  address: String
}

"""A crossing line, smart-detect zone or loiter zone on a Protect camera."""
type DetectionArea {
  id: ID!
  name: String
  kind: String!
  objectTypes: [String!]!
  direction: String
}

"""Detection-search filter vocabulary (the 'Find Anything' label groups)."""
type DetectionSearchLabels {
  colors: JSON
  vehicleTypes: JSON
  smartDetectTypes: JSON
  eventTypes: JSON
  groupType: JSON
  devices: JSON
  doorAccess: JSON
}

"""A UniFi network device (AP, switch, gateway)."""
type Device {
  mac: ID
  name: String
  model: String
  type: String
  version: String
  uptime: Int
  state: String
  ip: String
  ports: JSON
  systemStats: JSON
  generalTemperature: Float
  temperatures: JSON
  uptimeStats: JSON
  sourceApi: String

  """
  Public Integration inventory UUID, not a legacy resource ID. These IDs are scoped to the Integration inventory tool family — do not pass them to legacy resource tools.
  """
  integrationId: ID

  """Clients currently connected through this AP/switch."""
  portClients: [Client!]!
}

"""Paginated page of devices."""
type DevicePage {
  items: [Device!]!
  nextCursor: String
}

"""Wrapper dict containing the radio table for a device."""
type DeviceRadio {
  mac: ID
  name: String
  model: String
  radios: [RadioEntry!]!
  txPowerMode: String
  txPower: Int
  channel: Int
  ht: String
  minRssiEnabled: Boolean
  minRssi: Int
  assistedRoamingEnabled: Boolean
  antennaGain: Int
  antennaId: Int
  vwireEnabled: Boolean
  sensLevelEnabled: Boolean
  sensLevel: Int
}

"""A static DNS record served by the controller."""
type DnsRecord {
  id: ID
  hostname: String
  ip: String
  type: String
  ttl: Int
  enabled: Boolean!
  key: String
  value: String
  recordType: String
  port: Int
  priority: Int
  weight: Int
}

"""Paginated page of DNS records."""
type DnsRecordPage {
  items: [DnsRecord!]!
  nextCursor: String
}

"""A UniFi Access door (list + detail shape)."""
type Door {
  id: ID
  name: String
  location: String
  isOnline: Boolean
  isLocked: Boolean
  lockState: String
  lastEvent: JSON

  """Policies assigned to this door."""
  policyAssignments: [Policy!]!
}

"""A UniFi Access door group (list of doors)."""
type DoorGroup {
  id: ID
  name: String
  doorIds: [String!]!
  location: String
}

"""Paginated page of UniFi Access door groups."""
type DoorGroupPage {
  items: [DoorGroup!]!
  nextCursor: String
}

"""Paginated page of UniFi Access doors."""
type DoorPage {
  items: [Door!]!
  nextCursor: String
}

"""Per-door live status (lock state + last event)."""
type DoorStatus {
  doorId: ID
  name: String
  isLocked: Boolean
  lockState: String
  doorPositionStatus: String
  lastEventAt: String
  lastEventType: String
}

"""A DPI application classification entry."""
type DpiApplication {
  id: Int
  name: String
  categoryId: Int
}

"""Paginated page of DPI applications."""
type DpiApplicationPage {
  items: [DpiApplication!]!
  nextCursor: String
}

"""A DPI application category."""
type DpiCategory {
  id: Int
  name: String
}

"""Paginated page of DPI categories."""
type DpiCategoryPage {
  items: [DpiCategory!]!
  nextCursor: String
}

"""
DPI restriction rules (applications) and groups (categories); not traffic.
"""
type DpiStats {
  applications: JSON!
  categories: JSON!
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveDisk {
  """Bay number as printed on the NAS"""
  slotId: String

  """'disk' for a drive bay, 'cache' for an SSD cache slot"""
  bayType: String!

  """Disk state, such as optimal, or 'empty' for an empty bay"""
  state: String

  """Storage pool the disk belongs to"""
  poolId: String

  """RAID group the disk belongs to"""
  raidGroupId: String

  """Whether the disk is a global hot spare"""
  isGlobalHotSpare: Boolean

  """Whether the disk is a hot spare for its pool"""
  isLocalHotSpare: Boolean

  """Disk type, such as HDD or SSD"""
  type: String

  """Disk model"""
  model: String

  """Disk serial number"""
  serial: String

  """Disk firmware"""
  firmware: String

  """Raw disk size in bytes"""
  sizeBytes: BigInt

  """Spindle speed; absent for SSDs"""
  rpm: Int

  """SATA revision, such as SATA 3.3"""
  interface: String

  """ATA command set, such as ACS-4"""
  ataStandard: String

  """NVMe version, for NVMe disks"""
  nvmeVersion: String

  """Sector format, such as 512E"""
  sectorFormat: String

  """Disk temperature in degrees Celsius"""
  temperatureC: Float

  """SMART power-on hours"""
  powerOnHours: BigInt

  """SMART bad (reallocated) sector count"""
  badSectorCount: BigInt

  """SMART uncorrectable sector count"""
  uncorrectableSectorCount: BigInt

  """SMART read error rate"""
  readErrorRate: BigInt

  """SMART read error count"""
  smartReadErrorCount: BigInt

  """Why Drive flags the disk as at risk, if it does"""
  riskReasons: JSON

  """Why Drive considers the disk incompatible, if it does"""
  incompatibleReasons: JSON
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveDiskActivity {
  """Bay or cache slot number, as drive_list_disks reports it"""
  slotId: String

  """'disk' for a drive bay, 'cache' for an SSD cache slot"""
  bayType: String!

  """Disk type, such as HDD or SSD"""
  type: String

  """Buckets in the window for which Drive has data for this disk"""
  samplesWithData: Int!

  """Mean read throughput over those buckets, KB/s"""
  readKbpsAvg: Float

  """Highest bucket read throughput, KB/s"""
  readKbpsMax: Float

  """Mean write throughput over those buckets, KB/s"""
  writeKbpsAvg: Float

  """Highest bucket write throughput, KB/s"""
  writeKbpsMax: Float

  """Most recent temperature, degrees Celsius"""
  temperatureCLatest: Float

  """Highest temperature in the window"""
  temperatureCMax: Float

  """Most recent SMART bad sector count"""
  badSectorCountLatest: BigInt

  """
  Change in the bad sector count from the first to the last bucket with data; negative when the counter reset or the disk in the bay was replaced
  """
  badSectorCountIncrease: BigInt

  """
  Per-bucket values, oldest first. The REST route and the action return them only with include_samples: they add about 12 KB per disk per day at 15-minute buckets
  """
  samples: [DriveDiskStatsSample!]
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveDiskStats {
  """Start of the first bucket, ISO 8601 in UTC"""
  windowStart: String

  """End of the last bucket, ISO 8601 in UTC"""
  windowEnd: String

  """Length of each bucket in seconds"""
  intervalSeconds: Int

  """Buckets in the window"""
  sampleCount: Int

  """One entry per disk and cache SSD"""
  disks: [DriveDiskActivity!]
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveDiskStatsSample {
  """Start of the bucket, ISO 8601 in UTC"""
  time: String

  """Disk temperature in degrees Celsius"""
  temperatureC: Float

  """Average read throughput over the bucket, in KB/s"""
  readKbps: Float

  """Average write throughput over the bucket, in KB/s"""
  writeKbps: Float

  """SMART bad sector count"""
  badSectorCount: BigInt
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveFanProfile {
  """Profile in effect, as Drive reports it"""
  currentProfile: String

  """Web app name of that profile, such as Balanced"""
  currentLabel: String

  """Profiles the NAS offers"""
  availableProfiles: [DriveFanProfileOption!]
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveFanProfileOption {
  """Profile name as Drive reports it, such as default"""
  profile: String!

  """
  Name the Drive web app shows: Cooling (maximum cooling, more noise), Balanced (even cooling and noise) or Quiet (minimum noise, higher drive temperatures)
  """
  label: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveFileServices {
  """Whether SMB is enabled"""
  smbEnabled: Boolean

  """Whether NFS is enabled"""
  nfsEnabled: Boolean

  """Whether Time Machine (over SMB) is enabled; it requires SMB"""
  timeMachineEnabled: Boolean

  """Custom domain clients use, if one is set"""
  customDomain: String

  """Interfaces clients can connect to"""
  networkInterfaces: [DriveNetworkInterface!]
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveGroup {
  """
  Group id. These IDs are scoped to UniFi Drive user groups; do not pass them as user or shared drive ids.
  """
  id: String

  """Group name"""
  name: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveLogEntry {
  """When it was logged, ISO 8601 with the NAS's UTC offset"""
  time: String

  """low, medium, high or very_high"""
  severity: String

  """Log category, such as activity, storage or settings"""
  category: String

  """Log type within the category, such as storagePool"""
  type: String

  """Event name, such as DriveInserted"""
  event: String

  """Event title, such as Drive Inserted"""
  title: String

  """
  The entry as the Drive UI shows it; absent when Drive has no text for the event
  """
  message: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveLogPage {
  """Log entries, newest first"""
  entries: [DriveLogEntry!]!

  """
  Pass it back as cursor, with the same filters, for the next page; absent on the last page
  """
  nextCursor: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveNetworkInterface {
  """Interface name, such as enp0s0"""
  name: String

  """Port type, such as ethernet or sfp+"""
  interface: String

  """Whether the link is up"""
  connected: Boolean

  """Negotiated link speed, such as 10 GbE"""
  linkSpeed: String

  """Maximum link speed of the port"""
  maxSpeed: String

  """IP address clients connect to"""
  address: String

  """Interface MAC address"""
  mac: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveNetworkThroughput {
  """Data the NAS is receiving, in KB/s"""
  receiveKbps: Float

  """Data the NAS is sending, in KB/s"""
  transmitKbps: Float

  """When Drive took the sample, ISO 8601 with the console's UTC offset"""
  timestamp: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveNfsConnection {
  """Client IP address or hostname"""
  client: String

  """Whether the export uses async writes"""
  asyncWrites: Boolean

  """Shared drives it may mount"""
  sharedDrives: [DriveNfsSharedDriveGrant!]

  """
  Problems Drive reports for this connection, such as an unresolvable hostname
  """
  errorCodes: JSON
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveNfsSharedDriveGrant {
  """Shared drive id"""
  id: String

  """Shared drive name"""
  name: String

  """Shared drive status"""
  status: String

  """Shared drive encryption status"""
  encryptionStatus: String

  """rw (read-write) or ro (read-only)"""
  permission: String

  """Path a client mounts, <nas>:<export_path>"""
  exportPath: String
}

"""
Read-only access to UniFi Drive resources. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveQuery {
  """
  Identity, firmware and health of the NAS console. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  systemInfo(controller: ID!): DriveSystemInfo!

  """
  One page of the NAS's system log, newest first. Pass nextCursor back as cursor, with the same filters, for the next page. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  logs(controller: ID!, limit: Int! = 50, severities: [String!] = null, category: String = null, types: [String!] = null, keyword: String = null, scope: String = null, after: String = null, before: String = null, cursor: String = null): DriveLogPage!

  """
  Storage pools and their RAID groups. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  storagePools(controller: ID!): [DriveStoragePool!]!

  """
  Each storage pool's used space, split by what uses it. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  storageUsage(controller: ID!): [DriveStoragePoolUsage!]!

  """
  Drive bays and SSD cache slots with the disk in each and its SMART health. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  disks(controller: ID!, includeEmpty: Boolean! = false, includeCache: Boolean! = true): [DriveDisk!]!

  """
  The NAS's network throughput right now, in KB/s. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  networkThroughput(controller: ID!): DriveNetworkThroughput!

  """
  The NAS's fan mode and the modes it offers. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  fanProfile(controller: ID!): DriveFanProfile!

  """
  Each disk's temperature, throughput and bad sectors over the last hours (1 to 2160), summarized per disk, with per-bucket samples a query selects only when it needs them. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  diskStats(controller: ID!, hours: Int! = 24): DriveDiskStats!

  """
  Shared drives. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  sharedDrives(controller: ID!): [DriveSharedDrive!]!

  """
  One shared drive by id. Drive omits the protection flags and member count that the list includes. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  sharedDrive(controller: ID!, driveId: String!): DriveSharedDrive!

  """
  Every shared and personal drive's snapshot settings and state. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  snapshotOverview(controller: ID!): DriveSnapshotOverview!

  """
  One shared drive's snapshots, newest first, by the shared drive's name, not its id. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  snapshots(controller: ID!, sharedDriveName: String!): [DriveSnapshot!]!

  """
  Whether SMB, NFS and Time Machine are on, and the interfaces clients connect to. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  fileServices(controller: ID!): DriveFileServices!

  """
  NFS clients allowed to mount shared drives, with their export paths. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  nfsConnections(controller: ID!): [DriveNfsConnection!]!

  """
  Whether SMB Trash for personal drives is on, and whether every personal drive could move to it. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  smbAdvancedSettings(controller: ID!): DriveSmbAdvancedSettings!

  """
  The rsync service, its account (never its password) and whether SSH is on. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  rsyncSettings(controller: ID!): DriveRsyncSettings!

  """
  The NAS's users. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  users(controller: ID!): [DriveUser!]!

  """
  The UniFi OS user groups that shared drive access can be granted to. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
  """
  groups(controller: ID!): [DriveGroup!]!
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveRaidGroup {
  """RAID group number within the pool"""
  number: Int

  """RAID group id"""
  id: String

  """RAID level in effect now, such as raid1"""
  currentLevel: String

  """RAID level the pool is configured for, such as raid5"""
  configLevel: String

  """Disk failures the group survives now"""
  currentProtection: Int

  """Disk failures it survives at its configured level"""
  expectedProtection: Int

  """Recommended size in bytes for an added disk"""
  recommendedDiskSize: BigInt

  """Rebuild or expansion progress, as reported by Drive"""
  progress: Float

  """Estimated time remaining for that work, as reported by Drive"""
  estimate: Float

  """Whether this group is an SSD cache"""
  isSsdCache: Boolean

  """Why the group is a remnant, if it is one"""
  remnantReason: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveRsyncSettings {
  """Whether the rsync service is on"""
  enabled: Boolean

  """
  Whether a dedicated rsync account is set; its password is never returned
  """
  accountConfigured: Boolean

  """Username of that account, if Drive reports it"""
  accountUsername: String

  """
  Whether the console's SSH is on; rsync runs over SSH and does not work without it
  """
  sshEnabled: Boolean
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveSharedDrive {
  """
  Shared drive id. Pass it as shared_drives[].id to the drive_*_nfs_connection actions.
  """
  id: String

  """Shared drive name; NFS exports it as /var/nfs/shared/<name>"""
  name: String

  """Drive type, such as shared"""
  type: String

  """Drive status, such as active"""
  status: String

  """Storage pool the drive lives on"""
  storagePoolId: String

  """Quota in bytes; absent when unlimited"""
  quotaBytes: BigInt

  """Space used in bytes"""
  usedBytes: BigInt

  """The logged-in account's role on the drive"""
  role: String

  """Number of members with access"""
  memberCount: Int

  """Encryption status, such as unencrypted"""
  encryptionStatus: String

  """Whether snapshots are enabled"""
  snapshotEnabled: Boolean

  """Whether remote backup is enabled"""
  remoteBackupEnabled: Boolean
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveSmbAdvancedSettings {
  """
  Whether files removed over SMB from personal drives go to Trash (SMB Trash for Personal Drives)
  """
  personalDriveRecycleEnabled: Boolean

  """
  optimal when every personal drive can move removed files to Trash; migrateFirstFailed or migrateFailed when one or more cannot yet
  """
  personalDriveRecycleStatus: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveSnapshot {
  """
  Snapshot id. These IDs are scoped to one shared drive's snapshots in the UniFi Drive tool family.
  """
  id: String

  """Snapshot name; Drive leaves it empty unless one was given"""
  name: String

  """
  Drive's label for the snapshot, e.g. Scheduled Snapshot for one the schedule took
  """
  description: String

  """When the snapshot was taken"""
  createdAt: String

  """Whether the snapshot is locked, so Drive never removes it to make room"""
  locked: Boolean
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveSnapshotOverview {
  """Shared drives"""
  sharedDrives: [DriveSnapshotStatus!]

  """Personal drives"""
  personalDrives: [DriveSnapshotStatus!]
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveSnapshotSchedule {
  """Whether scheduled snapshots are on"""
  enabled: Boolean

  """
  daily, weekly or monthly; absent when the schedule is off and has no days set
  """
  frequency: String

  """Days of a weekly schedule, 0 (Sunday) to 6; empty otherwise"""
  weekdays: [Int!]

  """
  Days of a monthly schedule, 1 to 28, or L for the last day of the month; empty otherwise
  """
  monthdays: [String!]

  """Minutes between snapshots inside the daily window; absent when unset"""
  intervalMinutes: Int

  """Start of the daily window as H:MM, in the NAS console's local time"""
  startTime: String

  """End of the daily window as H:MM, in the NAS console's local time"""
  endTime: String
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveSnapshotStatus {
  """shared or personal"""
  driveType: String!

  """
  Shared drive id, the same id drive_list_shared_drives returns. These IDs are scoped to the UniFi Drive tool family.
  """
  sharedDriveId: String

  """
  Shared drive name; pass it to drive_list_snapshots as shared_drive_name
  """
  sharedDriveName: String

  """Shared drive status, such as active"""
  sharedDriveStatus: String

  """
  User id of a personal drive's owner. These IDs are scoped to UniFi Drive users; do not pass them as shared drive ids.
  """
  userId: String

  """Whether snapshot settings were ever saved for this drive"""
  configured: Boolean

  """
  Most snapshots Drive keeps for the drive; 0 when snapshots are not set up
  """
  snapshotLimit: Int

  """Snapshots the drive has now"""
  snapshotCount: Int

  """Locked snapshots, which Drive never removes to make room for new ones"""
  lockedCount: Int

  """Snapshots queued for deletion"""
  pendingDeletionCount: Int

  """Space the drive's snapshots hold, in bytes"""
  coverageBytes: BigInt

  """When the last snapshot was taken"""
  lastSnapshotTime: String

  """When the next scheduled snapshot is due"""
  nextSnapshotTime: String

  """Whether Drive has paused snapshots of this drive"""
  paused: Boolean

  """
  Why snapshots are paused, such as ErrSnapshotStorageLow, ErrSnapshotDeletionQueueFull or ErrSnapshotDeletionQueueStuck
  """
  pauseReason: String

  """Whether the drive is being restored from a snapshot"""
  restoring: Boolean

  """Encryption status, when Drive reports one"""
  encryptionStatus: String

  """Snapshot schedule"""
  schedule: DriveSnapshotSchedule
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveStoragePool {
  """Pool number"""
  number: Int

  """Storage pool id; shared drives name it as storage_pool_id"""
  id: String

  """Pool status, such as healthy or noDataProtectionYet"""
  status: String

  """RAID level chosen for the pool"""
  preferLevel: String

  """Volume type, such as lvm"""
  type: String

  """Usable capacity in bytes"""
  capacityBytes: BigInt

  """Used space in bytes"""
  usedBytes: BigInt

  """Used space as a percentage of capacity"""
  usedPercent: Float

  """Initialization status, such as successful"""
  initializingStatus: String

  """RAID group currently receiving writes"""
  activeRaidGroupId: String

  """RAID groups in the pool"""
  raidGroups: [DriveRaidGroup!]
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveStoragePoolUsage {
  """Storage pool id, the same id the storage pool list reports"""
  poolId: String

  """Usable capacity in bytes"""
  capacityBytes: BigInt

  """Used space in bytes"""
  usedBytes: BigInt

  """Free space in bytes"""
  availableBytes: BigInt

  """Used space as a percentage of capacity"""
  usedPercent: Float

  """Used by personal drives"""
  personalDrivesBytes: BigInt

  """Used by shared drives"""
  sharedDrivesBytes: BigInt

  """Used by snapshots, when Drive reports it"""
  snapshotsBytes: BigInt

  """Used by Microsoft 365 backups, when Drive reports it"""
  m365Bytes: BigInt

  """
  Used by everything else (system and other data): used space minus the parts above, as the Drive UI shows it. Absent when the pool has iSCSI or deduplication data, which Drive counts differently.
  """
  systemBytes: BigInt
}

"""
Identity, firmware and health of the UniFi OS console that runs UniFi Drive.
"""
type DriveSystemInfo {
  """Console name"""
  name: String

  """Console hostname"""
  hostname: String

  """Hardware model, such as UniFi Network Attached Storage Pro 8"""
  model: String

  """Hardware short name, such as UNASPRO8"""
  shortname: String

  """Console MAC address"""
  mac: String

  """UniFi OS firmware version"""
  firmwareVersion: String

  """Firmware version available as an update, if any"""
  firmwareUpdateAvailable: String

  """UniFi Drive application version"""
  driveVersion: String

  """UniFi Drive application version available as an update, if any"""
  driveUpdateAvailable: String

  """Console state, such as setup or updateAvailable"""
  deviceState: String

  """Whether initial setup is complete"""
  isSetup: Boolean

  """Seconds since the console started"""
  uptimeSeconds: Float

  """Console timezone"""
  timezone: String

  """CPU load reported by the console, 0 to 1"""
  cpuLoad: Float

  """CPU temperature in degrees Celsius"""
  cpuTemperatureC: Float

  """Total memory in KiB"""
  memoryTotalKb: BigInt

  """Available memory in KiB"""
  memoryAvailableKb: BigInt
}

"""
UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
"""
type DriveUser {
  """
  User id. These IDs are scoped to UniFi Drive users; do not pass them as shared drive or group ids.
  """
  id: String

  """Login name"""
  username: String

  """Display name"""
  fullName: String

  """Email address, when one is set"""
  email: String

  """Account status, such as active, deactivated or pending"""
  status: String

  """
  owner, admin or user, worked out as Drive's web app does: the console owner, any account with a role, or everyone else
  """
  accessLevel: String

  """Console roles the account holds, such as super_administrator"""
  roles: [String!]

  """Whether the user's personal drive is on"""
  personalDriveEnabled: Boolean

  """Whether the user must change the password at next login"""
  mustChangePassword: Boolean

  """Whether the account comes from Active Directory"""
  linkedToAd: Boolean

  """Whether the account has a UniFi SSO (UI.com) identity"""
  hasUiAccount: Boolean

  """When the account was created"""
  createdAt: String

  """Last login time; absent when the user never logged in"""
  lastLogin: String
}

"""A Dynamic DNS provider entry configured on the controller."""
type DynamicDns {
  id: ID
  siteId: String
  hostName: String
  service: String
  server: String
  login: String
  xPassword: String
  interface: String
  customService: String
  options: [String!]
}

"""Paginated page of Dynamic DNS entries."""
type DynamicDnsPage {
  items: [DynamicDns!]!
  nextCursor: String
}

"""A UniFi Protect event row (list + detail share this shape)."""
type Event {
  id: ID
  type: String
  start: String
  end: String
  score: Int
  smartDetectTypes: [String!]!
  camera: ID
  thumbnail: ID
  recognizedPersonId: ID
  recognizedPersonName: String
  recognizedPersonConfidence: Int
  recognizedPlateText: String
  recognizedPlateGroupId: ID
  recognizedPlateConfidence: Int
  detectedThumbnailId: ID
}

"""A curated event-log entry."""
type EventLog {
  id: ID
  key: String
  msg: String
  time: Int
  mac: String
  ip: String
  severity: String
  category: String
  subcategory: String
  event: String
  srcIp: String
  dstIp: String
  initiatorId: String
}

"""Paginated page of event-log entries."""
type EventLogPage {
  items: [EventLog!]!
  nextCursor: String
}

"""Paginated page of UniFi Protect events."""
type EventPage {
  items: [Event!]!
  nextCursor: String
}

"""Thumbnail metadata for a Protect event."""
type EventThumbnail {
  eventId: ID
  thumbnailId: ID
  thumbnailAvailable: Boolean
  imageBase64: String
  contentType: String
  message: String
  url: String
  sizeBytes: Int
}

"""Wrapper for exact event-key descriptors."""
type EventTypes {
  eventTypes: JSON!
}

"""A firewall address/port group (V1 /rest/firewallgroup)."""
type FirewallGroup {
  id: ID
  name: String
  groupType: String
  members: [String!]!
}

"""Paginated page of firewall groups."""
type FirewallGroupPage {
  items: [FirewallGroup!]!
  nextCursor: String
}

"""
Order of the user-defined firewall policies for a source/destination zone pair, read through the V2 API. These IDs are scoped to the V2 firewall policy tool family — do not pass them to the Integration API ordering queries or actions.
"""
type FirewallPolicyOrder {
  beforePredefinedIds: [String!]!
  afterPredefinedIds: [String!]!
}

"""
User-defined firewall policy ordering for a source/destination zone pair. Policy IDs in this object are UniFi integration-API UUIDs scoped to the ordering tool family — use them only with the matching reorder mutation. They do NOT correspond to the policy IDs returned by other controller-API firewall queries.
"""
type FirewallPolicyOrdering {
  ordering: JSON!
}

"""A firewall policy rule."""
type FirewallRule {
  id: ID
  name: String
  description: String
  action: String
  enabled: Boolean!
  predefined: Boolean!
  source: JSON
  destination: JSON
  index: Int
  protocol: String
  ipVersion: String
  connectionStateType: String
  connectionStates: [String!]!
  createAllowRespond: Boolean
  matchIpSec: Boolean
  matchOppositeProtocol: Boolean
  icmpTypename: String
  icmpV6Typename: String
  schedule: JSON
  logging: Boolean
}

"""Paginated page of firewall policies/rules."""
type FirewallRulePage {
  items: [FirewallRule!]!
  nextCursor: String
}

"""
A firewall zone from the V2 controller API. Its ID is a V2 ObjectID, not an Integration API UUID.
"""
type FirewallZone {
  id: ID
  name: String
  networks: JSON!
  defaultPolicy: String
}

"""Firmware status for the NVR plus its devices."""
type FirmwareStatus {
  nvr: JSON
  devices: JSON
  totalDevices: Int
  devicesWithUpdates: Int
}

"""UniFi gateway (USG) security / NAT / connection-tracking settings."""
type GatewaySettings {
  id: ID
  key: String
  geoIpFilteringEnabled: Boolean
  geoIpFilteringBlock: String
  geoIpFilteringCountries: String
  geoIpFilteringTrafficDirection: String
  synCookies: Boolean
  broadcastPing: Boolean
  receiveRedirects: Boolean
  sendRedirects: Boolean
  dnsVerification: JSON
  upnpEnabled: Boolean
  upnpNatPmpEnabled: Boolean
  upnpSecureMode: Boolean
  upnpWanInterface: String
  mssClamp: String
  ftpModule: Boolean
  greModule: Boolean
  h323Module: Boolean
  pptpModule: Boolean
  sipModule: Boolean
  tftpModule: Boolean
  offloadAccounting: Boolean
  offloadL2Blocking: Boolean
  offloadSch: Boolean
  icmpTimeout: Int
  otherTimeout: Int
  udpStreamTimeout: Int
  udpOtherTimeout: Int
  tcpEstablishedTimeout: Int
  tcpCloseTimeout: Int
  tcpCloseWaitTimeout: Int
  tcpFinWaitTimeout: Int
  tcpLastAckTimeout: Int
  tcpSynRecvTimeout: Int
  tcpSynSentTimeout: Int
  tcpTimeWaitTimeout: Int
  timeoutSettingPreference: String
  echoServer: String
  unbindWanMonitors: Boolean
}

"""Signature status from a legacy Network gateway device."""
type GatewaySignature {
  """
  Legacy Network device ID, not an Integration API UUID; null if unknown.
  """
  deviceId: ID

  """Gateway MAC address; null if unknown."""
  macAddress: String

  """Gateway display name; null if unknown."""
  name: String

  """Signature rule count; null if unknown."""
  ruleCount: BigInt

  """Signature update time in Unix milliseconds; null if unknown."""
  updateTime: BigInt

  """Controller signature type; null if unknown."""
  signatureType: String

  """Activation state; null if unknown."""
  isActivating: Boolean
}

"""Service health snapshot — smoke field for the GraphQL endpoint."""
type HealthSnapshot {
  ok: Boolean!
  version: String!
  pythonVersion: String!
}

"""
Bounded, read-only incident evidence: a unifi-incident-evidence-view (every source's coverage, failures and budget usage plus bounded record citations) or, with detail full, the whole unifi-incident-evidence document.
"""
type IncidentEvidence {
  """
  The unifi-incident-evidence-view, or the unifi-incident-evidence document with detail full. Check coverage_complete before treating an empty result as an all-clear.
  """
  document: JSON!
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceAccessPoint {
  """InnerSpace device id"""
  id: String

  """Device name"""
  name: String

  """Device model"""
  model: String

  """Device MAC address"""
  mac: String

  """Device serial number"""
  serial: String

  """InnerSpace floor plan id"""
  floorPlanId: String

  """Distance from the plan's left edge, in the unit"""
  x: Float

  """Distance from the plan's top edge, in the unit"""
  y: Float

  """True when the plan has no usable scale, so x and y are null"""
  scaleMissing: Boolean!

  """Mounting height, in the unit"""
  height: Float

  """Azimuth in degrees"""
  azimuth: Float

  """Mount: ceiling, wall, rack or floor"""
  mount: String

  """online or offline"""
  status: String

  """Length unit of the result: metric or imperial"""
  unit: String!
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceFloorPlan {
  """InnerSpace floor plan id"""
  id: String

  """Plan name"""
  name: String

  """Floor number"""
  floorNumber: Float

  """Plan units per metre, or per foot when imperial"""
  scalePerUnit: Float

  """Plan image width in pixels"""
  widthPx: Float

  """Plan image height in pixels"""
  heightPx: Float

  """Plan origin x as the console sent it"""
  originX: Float

  """Plan origin y as the console sent it"""
  originY: Float

  """InnerSpace site id"""
  siteId: String

  """Asset file name taken from the image URL"""
  imageFilename: String

  """The plan map's horizontal image scale, if sent"""
  imageScale: Float

  """The plan map's image offset (x, y)"""
  imageOffset: [Float!]

  """Length unit of the result: metric or imperial"""
  unit: String!
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceInventoryDevice {
  """InnerSpace device id"""
  id: String

  """Device name"""
  name: String

  """Device model"""
  model: String

  """Device MAC address"""
  mac: String

  """Device serial number"""
  serial: String
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpacePlacedDevice {
  """Placed device id"""
  id: String

  """InnerSpace floor plan id"""
  planId: String

  """Device title"""
  title: String

  """Product id"""
  productId: String

  """Device MAC address"""
  mac: String

  """Distance from the plan's left edge, in the unit"""
  x: Float

  """Distance from the plan's top edge, in the unit"""
  y: Float

  """Mounting height, in the unit"""
  height: Float

  """Mount: ceiling, wall, floor or rack"""
  mount: String

  """Base and point-of-view rotation quaternions"""
  rotation: JSON
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpacePlacedDevicePage {
  """Length unit of the result: metric or imperial"""
  unit: String!

  """InnerSpace floor plan id"""
  planId: String!

  """Placed devices, at most limit"""
  devices: [InnerSpacePlacedDevice!]!

  """The limit the list was cut at"""
  limit: Int!

  """Devices on the plan"""
  total: Int!

  """Whether the list was cut at limit"""
  truncated: Boolean!

  """True when the plan has no usable scale"""
  scaleMissing: Boolean!
}

"""
Image metadata of one floor plan. The API never returns the image; read it through the InnerSpace MCP server's plan image resource. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpacePlanAsset {
  """Asset file name"""
  filename: String!

  """Image media type"""
  contentType: String!

  """Image width in pixels"""
  widthPx: Float

  """Image height in pixels"""
  heightPx: Float

  """Plan units per metre, or per foot when imperial"""
  scalePerUnit: Float

  """The plan map's horizontal image scale, if sent"""
  imageScale: Float

  """The plan map's image offset (x, y)"""
  imageOffset: [Float!]

  """Length unit of the result: metric or imperial"""
  unit: String!
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpacePlanSummary {
  """InnerSpace floor plan id"""
  id: String

  """Plan title"""
  title: String

  """Plan order in the project"""
  ordering: Float

  """InnerSpace site id"""
  siteId: String

  """Plan units per metre, or per foot when imperial"""
  scalePerUnit: Float

  """True when the plan has no usable scale"""
  scaleMissing: Boolean!

  """The plan map's horizontal image scale, if sent"""
  imageScale: Float

  """The plan map's image offset (x, y)"""
  imageOffset: [Float!]

  """Number of shapes on the plan, by shape type"""
  shapeCounts: JSON!
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceProject {
  """Project identity"""
  project: InnerSpaceProjectInfo!

  """Length unit of the result: metric or imperial"""
  unit: String!

  """The project's plans, in order"""
  plans: [InnerSpacePlanSummary!]!

  """Wall types that are not deleted"""
  wallTypes: [InnerSpaceWallType!]!

  """Attenuation object types as the console sent them"""
  attenuationObjectTypes: JSON!

  """
  Every shape with converted geometry, when requested; device addresses are not carried
  """
  shapes: JSON
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceProjectInfo {
  """InnerSpace project id"""
  id: String

  """Project title"""
  title: String

  """Length unit of the result: metric or imperial"""
  unit: String!

  """When the project was created"""
  createdAt: String

  """When the project was last updated"""
  updatedAt: String
}

"""
Read-only access to UniFi InnerSpace resources. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceQuery {
  """
  Whether InnerSpace is installed and running on the console. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  status(controller: ID!): InnerSpaceStatus!

  """
  The InnerSpace project. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  project(controller: ID!, includeShapes: Boolean! = false, unit: String = null): InnerSpaceProject!

  """
  InnerSpace floor plans. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  floorPlans(controller: ID!, innerspaceSiteId: String = null): [InnerSpaceFloorPlan!]!

  """
  Walls of one InnerSpace floor plan. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  walls(controller: ID!, planId: String!, limit: Int! = 500, unit: String = null): InnerSpaceWallPage!

  """
  Devices placed on one InnerSpace floor plan. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  placedDevices(controller: ID!, planId: String!, limit: Int! = 500, unit: String = null): InnerSpacePlacedDevicePage!

  """
  InnerSpace access points. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  accessPoints(controller: ID!, innerspaceSiteId: String = null, unit: String = null): [InnerSpaceAccessPoint!]!

  """
  InnerSpace switches. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  switches(controller: ID!, innerspaceSiteId: String = null, unit: String = null): [InnerSpaceSwitch!]!

  """
  Adopted devices not yet placed on a plan. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  inventory(controller: ID!, innerspaceSiteId: String = null): [InnerSpaceInventoryDevice!]!

  """
  Image metadata of one InnerSpace floor plan. The image itself is read through the InnerSpace MCP server, never through this API. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
  """
  planAsset(controller: ID!, planId: String!): InnerSpacePlanAsset!
}

"""
Whether the InnerSpace application is installed and running on the UniFi OS console.
"""
type InnerSpaceStatus {
  """Whether the InnerSpace application is installed"""
  installed: Boolean!

  """Whether the InnerSpace application is running"""
  running: Boolean!

  """Installed version"""
  version: String

  """Version available as an update, if any"""
  updateAvailable: String
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceSwitch {
  """InnerSpace device id"""
  id: String

  """Device name"""
  name: String

  """Device model"""
  model: String

  """Switch type"""
  type: String

  """Device MAC address"""
  mac: String

  """Device serial number"""
  serial: String

  """InnerSpace floor plan id"""
  floorPlanId: String

  """Distance from the plan's left edge, in the unit"""
  x: Float

  """Distance from the plan's top edge, in the unit"""
  y: Float

  """True when the plan has no usable scale, so x and y are null"""
  scaleMissing: Boolean!

  """online or offline"""
  status: String

  """Length unit of the result: metric or imperial"""
  unit: String!
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceWall {
  """Wall id"""
  id: String

  """InnerSpace floor plan id"""
  planId: String

  """Start x from the plan's left edge, in the unit"""
  x1: Float

  """Start y from the plan's top edge, in the unit"""
  y1: Float

  """End x from the plan's left edge, in the unit"""
  x2: Float

  """End y from the plan's top edge, in the unit"""
  y2: Float

  """Wall length, in the unit"""
  length: Float

  """Wall material variant"""
  variant: String

  """Wall type id"""
  wallTypeId: String
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceWallPage {
  """Length unit of the result: metric or imperial"""
  unit: String!

  """InnerSpace floor plan id"""
  planId: String!

  """Walls, at most limit"""
  walls: [InnerSpaceWall!]!

  """The limit the list was cut at"""
  limit: Int!

  """Walls on the plan"""
  total: Int!

  """Whether the list was cut at limit"""
  truncated: Boolean!

  """True when the plan has no usable scale"""
  scaleMissing: Boolean!

  """Walls without two readable end points; coordinates are null"""
  unreadable: Int!
}

"""
UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
"""
type InnerSpaceWallType {
  """Wall type id"""
  id: String

  """Wall type name"""
  name: String

  """Attenuation in dB"""
  attenuationDb: Float

  """Display colour"""
  color: String

  """Whether the wall type is drawn transparent"""
  transparent: Boolean

  """Wall variant this type overrides"""
  overridesVariant: String
}

"""An address excluded from all IPS detection."""
type IpsExclusion {
  """source, destination, or both; null if unknown."""
  scope: String

  """Raw controller direction."""
  direction: String

  """Raw controller target kind, such as ip or subnet."""
  mode: String

  """Excluded address, subnet, or network."""
  target: String
}

"""One suppressed IPS signature for one target, or for all traffic."""
type IpsSuppression {
  """Signature ID."""
  signatureId: BigInt!

  """Signature generator ID."""
  gid: BigInt

  """Signature name."""
  signature: String

  """Signature category."""
  category: String

  """Raw controller type, such as all or track."""
  suppressionType: String

  """global, source, destination, or both; null if unknown."""
  scope: String

  """Raw controller direction."""
  direction: String

  """Raw controller target kind, such as ip or subnet."""
  mode: String

  """Suppressed address, subnet, or network."""
  target: String
}

"""IPS signature suppressions and detection exclusions for a site."""
type IpsSuppressions {
  """One entry per signature and target."""
  suppressions: [IpsSuppression!]!

  """Addresses excluded from all detection."""
  exclusions: [IpsExclusion!]!
}

"""
The `JSON` scalar type represents JSON values as specified by [ECMA-404](https://ecma-international.org/wp-content/uploads/ECMA-404_2nd_edition_december_2017.pdf).
"""
scalar JSON @specifiedBy(url: "https://ecma-international.org/wp-content/uploads/ECMA-404_2nd_edition_december_2017.pdf")

"""A UniFi Protect Known Face / assigned face recognition group."""
type KnownFace {
  id: ID
  name: String
  matchedName: String
  type: String
  imagePath: String
  enhancedPath: String
  detectionsCount: Int
  firstDetectedAt: String
  lastDetectedAt: String
  isNotificationEnabled: Boolean
  isDegraded: Boolean
  tags: JSON
  description: String
  createdAt: String
  metadata: JSON
}

"""Paginated page of UniFi Protect Known Faces."""
type KnownFacePage {
  items: [KnownFace!]!
  nextCursor: String
}

"""A UniFi Protect license-plate identity (vehicle recognition group)."""
type KnownLicensePlate {
  id: ID
  name: String
  matchedName: String
  type: String
  imagePath: String
  enhancedPath: String
  detectionsCount: Int
  firstDetectedAt: String
  lastDetectedAt: String
  isNotificationEnabled: Boolean
  isDegraded: Boolean
  tags: JSON
  description: String
  createdAt: String
  metadata: JSON
}

"""Paginated page of UniFi Protect license-plate identities."""
type KnownLicensePlatePage {
  items: [KnownLicensePlate!]!
  nextCursor: String
}

"""
A rule from the legacy (pre-zone-based) firewall engine, read from V1 /rest/firewallrule. Distinct from FirewallRule, which models the V2 zone-based engine: actions are lowercase (accept/drop/reject), rules belong to a ruleset rather than a zone pair, and source/destination are flat fields rather than nested objects. Read-only.
"""
type LegacyFirewallRule {
  id: ID
  name: String
  ruleset: String
  ruleIndex: Int
  action: String
  enabled: Boolean
  protocol: String
  protocolV6: String
  protocolMatchExcepted: Boolean
  srcAddress: String
  srcAddressIpv6: String
  srcPort: String
  srcMacAddress: String
  srcFirewallgroupIds: [String!]!
  srcNetworkconfId: String
  srcNetworkconfType: String
  dstAddress: String
  dstAddressIpv6: String
  dstPort: String
  dstFirewallgroupIds: [String!]!
  dstNetworkconfId: String
  dstNetworkconfType: String
  stateNew: Boolean
  stateEstablished: Boolean
  stateRelated: Boolean
  stateInvalid: Boolean
  icmpTypename: String
  icmpv6Typename: String
  ipsec: String
  logging: Boolean
  settingPreference: String
  noEdit: Boolean
  noDelete: Boolean
}

"""A UniFi Protect light (PIR-triggered floodlight)."""
type Light {
  id: ID
  mac: String
  name: String
  model: String
  state: String
  isPirMotionDetected: Boolean
  isLightOn: Boolean
  ledLevel: Int
  sensitivity: Int
  durationSeconds: Int
  statusLight: Boolean
}

"""Paginated page of UniFi Protect lights."""
type LightPage {
  items: [Light!]!
  nextCursor: String
}

"""A UniFi Protect liveview (multi-camera grid layout)."""
type Liveview {
  id: ID
  name: String
  layout: Int
  isDefault: Boolean
  isGlobal: Boolean
  ownerId: String
  cameras: [String!]!
  slots: JSON
  slotCount: Int
  cameraCount: Int

  """Cameras included in this liveview's slots."""
  cameraDetails: [Camera!]!
}

"""Paginated page of UniFi Protect liveviews."""
type LiveviewPage {
  items: [Liveview!]!
  nextCursor: String
}

"""Wrapper dict containing LLDP neighbors for a switch."""
type LldpNeighbors {
  name: String
  model: String
  lldpTable: [LldpRow!]!
}

"""A single LLDP neighbor row reported by a switch."""
type LldpRow {
  localPortIdx: Int
  chassisId: String
  portId: String
  systemName: String
  capabilities: [String!]!
}

"""Site-wide mDNS services; network scope is read-only."""
type MdnsSettings {
  id: ID
  siteId: String
  mode: String
  predefinedServices: [PredefinedService!]!
  customServices: [CustomService!]!
  enabledFor: String
  enabledForNetworkIds: [String!]!
}

"""
Read-only device management (mgmt) posture: device SSH state, key and credential presence. No credential, hash or key material is ever returned.
"""
type MgmtSettings {
  xSshEnabled: Boolean
  xSshUsername: String
  xSshAuthPasswordEnabled: Boolean
  xSshBindWildcard: Boolean
  sshKeysPresent: Boolean
  sshKeysCount: Int
  sshPasswordSet: Boolean
  sshPasswordHashSet: Boolean
  mgmtKeySet: Boolean
  apiTokenSet: Boolean
  debugToolsEnabled: Boolean
  autoUpgrade: Boolean
  autoUpgradeHour: Int
  advancedFeatureEnabled: Boolean
  unifiIdpEnabled: Boolean
  wifimanEnabled: Boolean
}

"""
A V2 controller NAT rule. Its ID is scoped to the NAT tool family; do not pass it to port-forward or Integration API tools.
"""
type NatRule {
  id: ID
  isPredefined: Boolean
  settingPreference: String
  type: String
  description: String
  enabled: Boolean
  ruleIndex: Int
  protocol: String
  ipVersion: String
  inInterface: String
  outInterface: String
  ipAddress: String
  port: String
  logging: Boolean
  exclude: Boolean
  pppoeUseBaseInterface: Boolean
  sourceFilter: JSON
  destinationFilter: JSON
}

"""Paginated page of V2 NAT rules."""
type NatRulePage {
  items: [NatRule!]!
  nextCursor: String
}

"""A UniFi LAN/VLAN network configuration."""
type Network {
  id: ID
  name: String
  purpose: String
  enabled: Boolean
  vlanEnabled: Boolean
  vlan: String
  ipSubnet: String
  subnet: String
  domainName: String
  dhcpdEnabled: Boolean
  dhcpdStart: String
  dhcpdStop: String
  dhcpdLeasetime: Int
  dhcpdGateway: String
  dhcpdGatewayEnabled: Boolean
  dhcpdDns1: String
  dhcpdDns2: String
  dhcpdDns3: String
  dhcpdDns4: String
  dhcpdDnsEnabled: Boolean
  dhcpdNtp1: String
  dhcpdNtp2: String
  dhcpdNtpEnabled: Boolean
  dhcpdWins1: String
  dhcpdWins2: String
  dhcpdWinsEnabled: Boolean
  dhcpdUnifiController: String
  dhcpdTftpServer: String
  dhcpdBootServer: String
  dhcpdBootFilename: String
  dhcpdBootEnabled: Boolean
  dhcpdConflictChecking: Boolean
  dhcpRelayEnabled: Boolean
  dhcpdIp1: String
  dhcpguardEnabled: Boolean
  autoScaleEnabled: Boolean
  igmpSnooping: Boolean
  igmpQuerierSwitches: JSON
  igmpFloodUnknownMulticast: Boolean

  """
  Whether mDNS is enabled for this network. Read-only and not authoritative: mDNS is configured site-wide on current UniFi Network versions, and this key only mirrors that site-wide scope — the mirror can go stale for hours, so treat the site-level setting as the source of truth (this server does not expose it). The controller accepts this field on the per-network write path but silently ignores it; unifi_update_network rejects it as read-only.
  """
  mdnsEnabled: Boolean
  networkIsolationEnabled: Boolean
  internetAccessEnabled: Boolean
  upnpLanEnabled: Boolean

  """
  V2 firewall-zone ID. These IDs are scoped to the V2 firewall/network tool family; do not pass Integration API firewall-zone UUIDs.
  """
  firewallZoneId: String
  wanType: String
  wanNetworkgroup: String
  wanDnsPreference: String
  wanDns1: String
  wanDns2: String
  wanLoadBalanceType: String
  wanLoadBalanceWeight: Int
  wanFailoverPriority: Int

  """Controller WAN-SLA configuration ID for this uplink."""
  wanSla: String
  reportWanEvent: Boolean
  wanSmartqEnabled: Boolean
  wanVlanEnabled: Boolean
  igmpProxyUpstream: Boolean
  igmpProxyFor: JSON
  macOverrideEnabled: Boolean
  wanIpAliases: JSON
  ipv6Enabled: Boolean
  wanTypeV6: String
  ipv6SettingPreference: String
  ipv6WanDelegationType: String
  wanDhcpv6PdSize: Int
  wanDhcpv6PdSizeAuto: Boolean
  wanIpv6DnsPreference: String
  wanIpv6Dns1: String
  wanIpv6Dns2: String
  ipv6InterfaceType: String
  ipv6Subnet: String
  ipv6Aliases: [String!]
  ipv6RaEnabled: Boolean
  ipv6RaPriority: String
  ipv6RaPreferredLifetime: Int
  ipv6ClientAddressAssignment: String
  ipv6PdInterface: String
  ipv6PdPrefixid: String
  ipv6PdAutoPrefixidEnabled: Boolean
  ipv6PdStart: String
  ipv6PdStop: String
  dhcpdv6Enabled: Boolean
  dhcpdv6AllowSlaac: Boolean
  dhcpdv6DnsAuto: Boolean
  dhcpdv6Dns1: String
  dhcpdv6Dns2: String
  dhcpdv6Dns3: String
  dhcpdv6Dns4: String
  dhcpdv6Leasetime: Int
  dhcpdv6Start: String
  dhcpdv6Stop: String
  sourceApi: String

  """
  Public Integration inventory UUID, not a legacy resource ID. These IDs are scoped to the Integration inventory tool family — do not pass them to legacy resource tools.
  """
  integrationId: ID

  """Clients on this network."""
  clients: [Client!]!
}

"""A network-health subsystem entry."""
type NetworkHealth {
  subsystem: String
  status: String
  numUser: Int
  numGuest: Int
  numIot: Int

  """
  Cumulative bytes received on this subsystem, when the controller sends a counter.
  """
  rxBytes: BigInt

  """
  Cumulative bytes transmitted on this subsystem, when the controller sends a counter.
  """
  txBytes: BigInt

  """
  Current receive rate on this subsystem in bytes per second (not a total).
  """
  rxBytesPerSec: Float

  """
  Current transmit rate on this subsystem in bytes per second (not a total).
  """
  txBytesPerSec: Float
}

"""Paginated page of network configurations."""
type NetworkPage {
  items: [Network!]!
  nextCursor: String
}

"""Read-only access to UniFi Network resources."""
type NetworkQuery {
  """List clients on the given controller/site (paginated)."""
  clients(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): ClientPage!

  """Look up a single client by MAC address."""
  client(controller: ID!, mac: ID!, site: String! = "default"): Client

  """List clients currently blocked from the network (paginated)."""
  blockedClients(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): BlockedClientPage!

  """Look up a client by IP address (online-presence check)."""
  clientByIp(controller: ID!, ip: String!, site: String! = "default"): ClientLookup

  """List devices on the given controller/site (paginated)."""
  devices(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): DevicePage!

  """Look up a single device by MAC address."""
  device(controller: ID!, mac: ID!, site: String! = "default"): Device

  """Get the radio configuration for a UniFi device with radios."""
  deviceRadio(controller: ID!, mac: ID!, site: String! = "default"): DeviceRadio

  """Get LLDP neighbors reported by a switch."""
  lldpNeighbors(controller: ID!, deviceMac: ID!, site: String! = "default"): LldpNeighbors

  """Get per-outlet state for a UniFi Smart Power PDU (UP6 / USP-Strip)."""
  pduOutlets(controller: ID!, mac: ID!, site: String! = "default"): PduOutlets

  """List rogue (unknown) APs detected within a window (paginated)."""
  rogueAps(controller: ID!, site: String! = "default", withinHours: Int! = 24, limit: Int! = 50, cursor: String = null): RogueApPage!

  """List RF-scan results for a specific access point."""
  rfScanResults(controller: ID!, apMac: ID!, site: String! = "default"): [RfScanResult!]!

  """List wireless channels allowed by the regulatory domain."""
  availableChannels(controller: ID!, site: String! = "default"): [AvailableChannel!]!

  """Get the gateway speedtest status (idle/running + last results)."""
  speedtestStatus(controller: ID!, gatewayMac: ID!, site: String! = "default"): SpeedtestStatus

  """
  List configured LAN/VLAN networks on the given controller/site (paginated).
  """
  networks(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): NetworkPage!

  """
  What references a network: Wi-Fi networks, port profiles, switch-port overrides, V2 firewall policies and clients. network_id is the network's _id from the networks field. Each family is read on its own; a family whose read failed is listed in unavailable instead of being reported as empty.
  """
  networkReferences(controller: ID!, networkId: ID!, site: String! = "default", includeClients: Boolean! = true): NetworkReferences

  """
  Look up a single LAN/VLAN network by id. (Named ``networkDetail`` because ``network`` is reserved for the namespace.)
  """
  networkDetail(controller: ID!, id: ID!, site: String! = "default"): Network

  """Get the controller's network-health subsystems list."""
  networkHealth(controller: ID!, site: String! = "default"): [NetworkHealth!]!

  """
  List WLAN/SSID configurations on the given controller/site (paginated).
  """
  wlans(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): WlanPage!

  """Look up a single WLAN/SSID by id."""
  wlan(controller: ID!, id: ID!, site: String! = "default"): Wlan

  """List configured VPN clients (outbound tunnels) (paginated)."""
  vpnClients(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): VpnClientPage!

  """Look up a single VPN client by id."""
  vpnClient(controller: ID!, id: ID!, site: String! = "default"): VpnClient

  """List configured VPN servers (inbound tunnels) (paginated)."""
  vpnServers(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): VpnServerPage!

  """Look up a single VPN server by id."""
  vpnServer(controller: ID!, id: ID!, site: String! = "default"): VpnServer

  """List static DNS records on the given controller/site (paginated)."""
  dnsRecords(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): DnsRecordPage!

  """Look up a single DNS record by id."""
  dnsRecord(controller: ID!, id: ID!, site: String! = "default"): DnsRecord

  """
  List Dynamic DNS provider entries on the given controller/site (paginated).
  """
  dynamicDns(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): DynamicDnsPage!

  """Look up a single Dynamic DNS entry by id."""
  dynamicDnsEntry(controller: ID!, id: ID!, site: String! = "default"): DynamicDns

  """List configured static routes (paginated)."""
  routes(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): RoutePage!

  """Look up a single static route by id."""
  route(controller: ID!, id: ID!, site: String! = "default"): Route

  """List the gateway's active kernel routing-table entries (paginated)."""
  activeRoutes(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): ActiveRoutePage!

  """List traffic-route policies (V2 /trafficroutes) (paginated)."""
  trafficRoutes(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): TrafficRoutePage!

  """Look up a single traffic-route policy by id."""
  trafficRoute(controller: ID!, id: ID!, site: String! = "default"): TrafficRoute

  """List firewall policies/rules on the given controller/site (paginated)."""
  firewallPolicies(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): FirewallRulePage!

  """Look up a single firewall policy/rule by id."""
  firewallPolicy(controller: ID!, id: ID!, site: String! = "default"): FirewallRule

  """List firewall address/port groups (paginated)."""
  firewallGroups(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): FirewallGroupPage!

  """Look up a single firewall group by id."""
  firewallGroup(controller: ID!, id: ID!, site: String! = "default"): FirewallGroup

  """List firewall zones (typically a small flat list — no pagination)."""
  firewallZones(controller: ID!, site: String! = "default"): [FirewallZone!]!

  """
  List legacy (pre-zone-based) firewall rules. Sites still running the legacy engine return no zone-based policies or zones, so an empty firewallPolicies result does not mean no firewall rules are configured — check here as well.
  """
  legacyFirewallRules(controller: ID!, site: String! = "default"): [LegacyFirewallRule!]!

  """
  Get user-defined firewall policy ordering for a source/destination zone pair. Returns policy IDs from the UniFi integration API (UUIDs); these IDs are scoped to the ordering tool family and do NOT correspond to the policy IDs returned by firewallPolicies or other controller-API firewall queries. Requires a UniFi API key (UNIFI_API_KEY).
  """
  firewallPolicyOrdering(controller: ID!, sourceFirewallZoneId: String!, destinationFirewallZoneId: String!, site: String! = "default"): FirewallPolicyOrdering!

  """
  Get the order of the user-defined firewall policies for a source/destination zone pair through the V2 API. Requires Network session credentials. These IDs are scoped to the V2 firewall policy tool family — do not pass them to the Integration API ordering queries or actions.
  """
  firewallPolicyOrder(controller: ID!, sourceZoneId: String!, destinationZoneId: String!, site: String! = "default"): FirewallPolicyOrder!

  """List QoS rules on the given controller/site (paginated)."""
  qosRules(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): QosRulePage!

  """Look up a single QoS rule by id."""
  qosRule(controller: ID!, id: ID!, site: String! = "default"): QosRule

  """List DPI applications (paginated)."""
  dpiApplications(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): DpiApplicationPage!

  """List DPI categories (paginated)."""
  dpiCategories(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): DpiCategoryPage!

  """List content filters on the given controller/site (paginated)."""
  contentFilters(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): ContentFilterPage!

  """Look up a single content filter by id."""
  contentFilter(controller: ID!, id: ID!, site: String! = "default"): ContentFilter

  """List ACL rules on the given controller/site (paginated)."""
  aclRules(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): AclRulePage!

  """Look up a single ACL rule by id."""
  aclRule(controller: ID!, id: ID!, site: String! = "default"): AclRule

  """List OON (out-of-network) policies (paginated)."""
  oonPolicies(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): OonPolicyPage!

  """Look up a single OON policy by id."""
  oonPolicy(controller: ID!, id: ID!, site: String! = "default"): OonPolicy

  """
  List V2 NAT rules in descending controller ID order. These IDs are scoped to the V2 NAT tool family — do not pass them to port-forward or Integration API tools.
  """
  natRules(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): NatRulePage!

  """
  Get a V2 NAT rule by its NAT-family ID; do not use port-forward or Integration API IDs.
  """
  natRule(controller: ID!, id: ID!, site: String! = "default"): NatRule

  """List port forwards on the given controller/site (paginated)."""
  portForwards(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): PortForwardPage!

  """Look up a single port forward by id."""
  portForward(controller: ID!, id: ID!, site: String! = "default"): PortForward

  """Site dashboard timeseries (all-points)."""
  dashboardStats(controller: ID!, site: String! = "default", durationHours: Int! = 1): [StatPoint!]!

  """Network-wide stats timeseries."""
  networkStats(controller: ID!, site: String! = "default", durationHours: Int! = 1): [StatPoint!]!

  """Gateway stats timeseries."""
  gatewayStats(controller: ID!, site: String! = "default", durationHours: Int! = 24): [StatPoint!]!

  """Per-client stats timeseries (by MAC)."""
  clientStats(controller: ID!, mac: ID!, site: String! = "default", durationHours: Int! = 1): [StatPoint!]!

  """Per-device stats timeseries (by MAC)."""
  deviceStats(controller: ID!, mac: ID!, site: String! = "default", durationHours: Int! = 1): [StatPoint!]!

  """Per-client DPI traffic breakdown."""
  clientDpiTraffic(controller: ID!, mac: ID!, site: String! = "default"): [StatPoint!]!

  """Site-wide DPI traffic breakdown."""
  siteDpiTraffic(controller: ID!, site: String! = "default"): [StatPoint!]!

  """
  DPI restriction rules (applications) and groups (categories); not traffic.
  """
  dpiStats(controller: ID!, site: String! = "default"): DpiStats

  """List recent controller events (paginated)."""
  eventLog(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): EventLogPage!

  """List active alerts (paginated)."""
  alerts(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): EventLogPage!

  """List recent anomalies (paginated)."""
  anomalies(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): EventLogPage!

  """List recent IPS/IDS events (paginated)."""
  ipsEvents(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): EventLogPage!

  """List controller alarms (paginated)."""
  alarms(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): AlarmPage!

  """Get controller system info (build, uptime, hardware)."""
  systemInfo(controller: ID!, site: String! = "default"): SystemInfo

  """Get site-level settings (locale, timezone, advanced)."""
  siteSettings(controller: ID!, site: String! = "default"): SiteSettings

  """Get SNMP settings."""
  snmpSettings(controller: ID!, site: String! = "default"): SnmpSettings

  """Get site-wide mDNS service settings and read-only network scope."""
  mdnsSettings(controller: ID!, site: String! = "default"): MdnsSettings

  """
  Get Teleport VPN settings: enabled state and client address range (subnet_cidr).
  """
  teleportSettings(controller: ID!, site: String! = "default"): TeleportSettings

  """
  Get site-wide threat management (IDS/IPS) and traffic identification settings.
  """
  threatManagementSettings(controller: ID!, site: String! = "default"): ThreatManagementSettings

  """List IPS signature suppressions and detection exclusions."""
  ipsSuppressions(controller: ID!, site: String! = "default"): IpsSuppressions!

  """
  Get CyberSecure threat posture for HOUR, DAY, WEEK, or MONTH using a Network session.
  """
  threatPosture(controller: ID!, site: String! = "default", period: String! = "DAY"): ThreatPosture

  """
  Collect bounded, read-only Network event evidence for one incident window as a unifi-incident-evidence-view (coverage plus bounded record citations), or with detail full the whole unifi-incident-evidence document. Stops at the first spent budget and says so; check coverage_complete before treating an empty result as an all-clear. Not cached.
  """
  incidentEvidence(controller: ID!, start: String!, end: String!, site: String! = "default", deviceMacs: [String!] = null, locationId: String = null, maxWindowSeconds: Int! = 86400, maxEvents: Int! = 1000, maxCalls: Int! = 20, maxElapsedMs: Int! = 30000, mappings: JSON = null, detail: String! = "view", maxRecordsReturned: Int = null, resumeAfter: String = null): IncidentEvidence!

  """
  Get device management (mgmt) settings: device SSH, debug tools, automatic upgrades.
  """
  mgmtSettings(controller: ID!, site: String! = "default"): MgmtSettings

  """Get gateway (USG) security / NAT / connection-tracking settings."""
  gatewaySettings(controller: ID!, site: String! = "default"): GatewaySettings

  """
  Get exact event keys sampled from the controller's 1,000 most recent events within the last 7 days.
  """
  eventTypes(controller: ID!, site: String! = "default"): EventTypes

  """Get auto-backup schedule + retention settings."""
  autobackupSettings(controller: ID!, site: String! = "default"): AutoBackupSettings

  """List controller backups (paginated)."""
  backups(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): BackupPage!

  """List recent speedtest results (paginated)."""
  speedtestResults(controller: ID!, site: String! = "default", durationHours: Int! = 24, limit: Int! = 50, cursor: String = null): SpeedtestResultPage!

  """List top-traffic clients within a window."""
  topClients(controller: ID!, site: String! = "default", withinHours: Int! = 24): [TopClient!]!

  """List hotspot vouchers on the given controller/site (paginated)."""
  vouchers(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): VoucherPage!

  """Look up a single hotspot voucher by id."""
  voucher(controller: ID!, id: ID!, site: String! = "default"): Voucher

  """List a client's association sessions (paginated)."""
  clientSessions(controller: ID!, site: String! = "default", mac: String = null, durationHours: Int! = 24, limit: Int! = 50, cursor: String = null): ClientSessionPage!

  """Get a client's current WiFi parameters (signal, rates)."""
  clientWifiDetails(controller: ID!, mac: ID!, site: String! = "default"): ClientWifiDetails

  """Query historical traffic flows (Insights > Flows), paginated."""
  trafficFlows(controller: ID!, site: String! = "default", withinHours: Int! = 24, timeFrom: BigInt = null, timeTo: BigInt = null, searchText: String = null, risk: [String!] = null, action: [String!] = null, direction: [String!] = null, protocol: [String!] = null, service: [String!] = null, sourceMac: [String!] = null, sourceIp: [String!] = null, sourceName: [String!] = null, sourceNetworkId: [String!] = null, sourcePort: [Int!] = null, destinationDomain: [String!] = null, destinationIp: [String!] = null, destinationPort: [Int!] = null, destinationRegion: [String!] = null, pageSize: Int! = 100, cursor: String = null): TrafficFlowPage!

  """
  Aggregated Insights > Flows summary (risk/region counts + Top-Talkers).
  """
  trafficFlowStatistics(controller: ID!, site: String! = "default", period: String! = "DAY", top: Int! = 10): TrafficFlowStatistics!

  """List switch port profiles on the given controller/site (paginated)."""
  portProfiles(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): PortProfilePage!

  """Look up a single switch port profile by id."""
  portProfile(controller: ID!, id: ID!, site: String! = "default"): PortProfile

  """
  Get the port-override wrapper for a switch (name/model + per-port overrides).
  """
  switchPorts(controller: ID!, deviceMac: ID!, site: String! = "default"): SwitchPorts

  """Get the per-port stats wrapper for a switch (name/model + port_table)."""
  portStats(controller: ID!, deviceMac: ID!, site: String! = "default"): PortStats

  """Get switch capabilities (caps dict + STP / dot1x flags)."""
  switchCapabilities(controller: ID!, deviceMac: ID!, site: String! = "default"): SwitchCapabilities

  """List AP groups on the given controller/site (paginated)."""
  apGroups(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): ApGroupPage!

  """Look up a single AP group by id."""
  apGroup(controller: ID!, id: ID!, site: String! = "default"): ApGroup

  """
  List network member client groups on the given controller/site (paginated).
  """
  clientGroups(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): ClientGroupPage!

  """Look up a single network member client group by id."""
  clientGroup(controller: ID!, id: ID!, site: String! = "default"): ClientGroup

  """
  List QoS user groups (V1 /rest/usergroup) on the given controller/site (paginated).
  """
  userGroups(controller: ID!, site: String! = "default", limit: Int! = 50, cursor: String = null): UserGroupPage!

  """Look up a single QoS user group by id."""
  userGroup(controller: ID!, id: ID!, site: String! = "default"): UserGroup
}

"""
What references a network: Wi-Fi networks, port profiles, switch-port overrides, V2 firewall policies and clients. network_id is the network's _id from the networks field. Each family is read on its own; a family whose read failed is listed in unavailable instead of being reported as empty.
"""
type NetworkReferences {
  networkId: String!
  name: String
  references: JSON!
  counts: JSON!
  unavailable: [String!]!
}

"""An out-of-network (OON) policy entry."""
type OonPolicy {
  id: ID
  name: String
  enabled: Boolean!
  targetType: String
  targets: JSON
  appliesTo: JSON
  secure: JSON
  qos: JSON
  qosEnabled: Boolean
  route: JSON
  routeEnabled: Boolean
  restrictionLevel: String
}

"""Paginated page of OON (out-of-network) policies."""
type OonPolicyPage {
  items: [OonPolicy!]!
  nextCursor: String
}

"""A single outlet on a UniFi Smart Power PDU (UP6 / USP-Strip)."""
type PduOutletEntry {
  index: Int
  name: String
  hasRelay: Boolean
  hasMetering: Boolean
  relayState: Boolean
  cycleEnabled: Boolean
  overrideRelayState: Boolean
  overrideCycleEnabled: Boolean
  hasOverride: Boolean!
}

"""Wrapper dict containing per-outlet state for a Smart Power PDU."""
type PduOutlets {
  mac: ID
  name: String
  model: String
  outlets: [PduOutletEntry!]!
}

"""A UniFi Access policy (who-can-access-what binding)."""
type Policy {
  id: ID
  name: String
  scheduleId: String
  doorIds: [String!]!
  userGroupIds: [String!]!
  enabled: Boolean!
}

"""Paginated page of UniFi Access policies."""
type PolicyPage {
  items: [Policy!]!
  nextCursor: String
}

"""A port-forward rule (V1 /rest/portforward entry)."""
type PortForward {
  id: ID
  name: String
  enabled: Boolean!
  fwdProtocol: String
  dstPort: String
  destinationIp: String
  fwdPort: String
  fwdIp: String
  src: String
  log: Boolean!
}

"""Paginated page of port forwards."""
type PortForwardPage {
  items: [PortForward!]!
  nextCursor: String
}

"""A single port-override row on a switch."""
type PortOverrideRow {
  portIdx: Int
  name: String
  portconfId: String
  poeMode: String
  opMode: String
}

"""A switch port profile (PoE / VLAN tagging template)."""
type PortProfile {
  id: ID
  name: String
  forward: String
  taggedVlanMgmt: String
  nativeNetworkconfId: String
  taggedNetworkconfIds: [String!]!
  excludedNetworkconfIds: [String!]
  voiceNetworkconfId: String
  poeMode: String
  isolation: Boolean
  stpPortMode: Boolean
  stpEdgeState: String
  stpBpduGuardEnabled: Boolean
  stpUplink: Boolean
  dot1xCtrl: String
  stormctrlBcastEnabled: Boolean
  stormctrlBcastRate: Int
  stormctrlMcastEnabled: Boolean
  stormctrlMcastRate: Int
  stormctrlUcastEnabled: Boolean
  stormctrlUcastRate: Int
}

"""Paginated page of switch port profiles."""
type PortProfilePage {
  items: [PortProfile!]!
  nextCursor: String
}

"""A single port-table row reporting per-port stats."""
type PortStatRow {
  portIdx: Int
  name: String
  enable: Boolean!
  speed: Int
  duplex: Boolean
  txBytes: Int!
  rxBytes: Int!
  txPackets: Int!
  rxPackets: Int!
  txDropped: Int!
  rxDropped: Int!
  poeEnable: Boolean!
  poeMode: String
  poePower: Float
}

"""Wrapper dict containing the per-port stats table for a switch."""
type PortStats {
  name: String
  model: String
  portTable: [PortStatRow!]!
}

type PredefinedService {
  code: String
}

"""UniFi Protect NVR health snapshot (pass-through)."""
type ProtectHealth {
  cpu: JSON
  memory: JSON
  storage: JSON
  isUpdating: Boolean
  uptimeSeconds: Int
}

"""Read-only access to UniFi Protect resources."""
type ProtectQuery {
  """
  Collect bounded, read-only Protect event evidence for one incident window as a unifi-incident-evidence-view (coverage plus bounded record citations), or with detail full the whole unifi-incident-evidence document. Each camera ID is its own source. Stops at the first spent budget and says so; check coverage_complete before treating an empty result as an all-clear. Not cached.
  """
  incidentEvidence(controller: ID!, start: String!, end: String!, cameraIds: [String!] = null, locationId: String = null, maxWindowSeconds: Int! = 86400, maxEvents: Int! = 1000, maxCalls: Int! = 20, maxElapsedMs: Int! = 30000, mappings: JSON = null, detail: String! = "view", maxRecordsReturned: Int = null, resumeAfter: String = null): IncidentEvidence!

  """List cameras on the Protect controller (paginated)."""
  cameras(controller: ID!, limit: Int! = 50, cursor: String = null): CameraPage!

  """Look up a single Protect camera by id."""
  camera(controller: ID!, id: ID!): Camera

  """Get analytics summary for a Protect camera."""
  cameraAnalytics(controller: ID!, id: ID!): CameraAnalytics

  """
  List a camera's crossing lines, smart-detect zones and loiter zones (id, name, kind, objectTypes, and direction for lines), read fresh from the NVR.
  """
  cameraDetectionAreas(controller: ID!, id: ID!): CameraDetectionAreas

  """Get the stream catalog (channels + RTSPS URLs) for a camera."""
  cameraStreams(controller: ID!, id: ID!): CameraStreams

  """Capture a JPEG snapshot from a camera (metadata only)."""
  snapshot(controller: ID!, id: ID!, width: Int = null, height: Int = null): Snapshot

  """List assigned Protect Known Faces / named face recognition groups."""
  knownFaces(controller: ID!, limit: Int! = 50, cursor: String = null, minConfidence: Int! = 30, includeInterest: Boolean! = true, groupTypes: [String!] = null, orderBy: String! = "name", orderDirection: String! = "asc"): KnownFacePage!

  """
  List UniFi Protect license-plate identities (vehicle recognition groups). Each entry's id is the value to use in a `license_plate_known` alarm-rule condition.
  """
  knownLicensePlates(controller: ID!, limit: Int! = 50, cursor: String = null, minConfidence: Int! = 30, includeInterest: Boolean! = true, groupTypes: [String!] = null, orderBy: String! = "name", orderDirection: String! = "asc"): KnownLicensePlatePage!

  """
  Search detections across cameras via Protect's 'Find Anything' filter vocabulary. Pass labels of the form 'prefix:value' (e.g. 'vehicleType:truck'); use detectionSearchLabels to discover legal values.
  """
  searchDetections(controller: ID!, labels: [String!]!, limit: Int! = 100, order: String! = "desc", excludeMotion: Boolean! = true, minConfidence: Int = null): [SmartDetection!]!

  """The detection-search filter vocabulary ('Find Anything' label groups)."""
  detectionSearchLabels(controller: ID!): DetectionSearchLabels!

  """List paired Protect chimes (paginated)."""
  chimes(controller: ID!, limit: Int! = 50, cursor: String = null): ChimePage!

  """Get the alarm system arm-state snapshot."""
  alarmStatus(controller: ID!): AlarmStatus

  """
  List configured alarm profiles ({profiles, count, complete, coverageNotice}), including each profile's state and state_set_at timestamp. Use arm_compatible to determine whether a profile id can be passed to the arm and disarm actions.
  """
  alarmProfiles(controller: ID!): AlarmProfileList

  """
  List configured alarm rules / Alarm Manager automations ({rules, count}).
  """
  alarmRules(controller: ID!): AlarmRuleList

  """Fetch a single alarm rule (automation) by id."""
  alarmRule(controller: ID!, id: ID!): AlarmRule

  """
  Triggers and actions the Alarm Manager accepts in rules ({triggers, actions, scope}); their ids are the trigger_id/action_id values a rule takes. search filters by id, title or category; includeSchemas adds each entry's options_schema and the scope schema.
  """
  alarmCatalog(controller: ID!, search: String = null, includeSchemas: Boolean! = false): AlarmCatalog

  """List Protect events (paginated, most recent first)."""
  events(controller: ID!, limit: Int! = 50, cursor: String = null, eventType: String = null, cameraId: String = null): EventPage!

  """Look up a single Protect event by id."""
  event(controller: ID!, id: ID!): Event

  """Get the thumbnail for a Protect event."""
  eventThumbnail(controller: ID!, eventId: ID!, width: Int = null, height: Int = null): EventThumbnail

  """List Protect smart-detection events (paginated, most recent first)."""
  smartDetections(controller: ID!, limit: Int! = 50, cursor: String = null, cameraId: String = null, detectionType: String = null, minConfidence: Int = null): SmartDetectionPage!

  """
  List Protect recording windows for a camera. UniFi Protect exposes a single continuous recording window per camera.
  """
  recordings(controller: ID!, cameraId: ID!, limit: Int! = 50, cursor: String = null): RecordingPage!

  """Get current recording state for one or all cameras ({cameras, count})."""
  recordingStatus(controller: ID!, cameraId: String = null): RecordingStatusList

  """List Protect lights (PIR-triggered floodlights)."""
  lights(controller: ID!, limit: Int! = 50, cursor: String = null): LightPage!

  """List Protect sensors (motion / leak / temperature)."""
  sensors(controller: ID!, limit: Int! = 50, cursor: String = null): SensorPage!

  """List Protect liveviews (multi-camera grid layouts)."""
  liveviews(controller: ID!, limit: Int! = 50, cursor: String = null): LiveviewPage!

  """Get the NVR-level system info snapshot."""
  systemInfo(controller: ID!): ProtectSystemInfo

  """Get the NVR health snapshot (cpu / memory / storage)."""
  health(controller: ID!): ProtectHealth

  """Get firmware status for the NVR plus its devices."""
  firmwareStatus(controller: ID!): FirmwareStatus

  """List Protect viewers ({viewers, count})."""
  viewers(controller: ID!): ViewerList
}

"""UniFi Protect NVR-level system info (pass-through)."""
type ProtectSystemInfo {
  id: ID
  name: String
  model: String
  firmwareVersion: String
  version: String
  host: String
  mac: String
  uptimeSeconds: Int
  upSince: String
  isUpdating: Boolean
  storage: JSON
  cameraCount: Int
  lightCount: Int
  sensorCount: Int
  viewerCount: Int
  chimeCount: Int
}

"""A QoS rate-limit rule (V2 /qos-rules entry)."""
type QosRule {
  id: ID
  name: String
  enabled: Boolean!
  interface: String
  direction: String
  bandwidthLimitKbps: Int
  targetIpAddress: String
  targetSubnet: String
  dscpValue: Int
  rateMaxDown: Int
  rateMaxUp: Int
  priority: Int
}

"""Paginated page of QoS rules."""
type QosRulePage {
  items: [QosRule!]!
  nextCursor: String
}

type Query {
  """Liveness probe; mirrors GET /v1/health/ready."""
  health: HealthSnapshot!

  """Read-only access to UniFi Network resources."""
  network: NetworkQuery!

  """Read-only access to UniFi Protect resources."""
  protect: ProtectQuery!

  """Read-only access to UniFi Access resources."""
  access: AccessQuery!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  sitemanager: SiteManagerQuery!

  """Read-only access to UniFi InnerSpace resources."""
  innerspace: InnerSpaceQuery!

  """Read-only access to UniFi Drive resources."""
  drive: DriveQuery!
}

"""Radio configuration entry on a UniFi device with radios."""
type RadioEntry {
  name: String
  radio: String
  channel: Int
  ht: String
  txPower: Int
  txPowerMode: String
  currentChannel: Int
  currentTxPower: Int
  numSta: Int

  """Selected antenna id from the device's antenna_table, when it has one."""
  antennaId: Int
}

"""A UniFi Protect recording window for a camera."""
type Recording {
  id: ID
  type: String
  camera: ID
  start: String
  end: String
  fileSize: Int

  """The camera this recording came from."""
  cameraDetail: Camera
}

"""Paginated page of UniFi Protect recording windows."""
type RecordingPage {
  items: [Recording!]!
  nextCursor: String
}

"""Recording-status wrapper for protect_get_recording_status."""
type RecordingStatusList {
  cameras: JSON
  count: Int
}

"""A single RF-scan result row reported by an AP."""
type RfScanResult {
  bssid: ID
  ssid: String
  channel: Int
  signalDbm: Int
  capturedAt: Int
}

"""A rogue (unknown) AP detected by the controller."""
type RogueAp {
  bssid: ID
  ssid: String
  channel: Int
  signalDbm: Int
  lastSeen: Int
  isKnown: Boolean!
}

"""Paginated page of detected rogue APs."""
type RogueApPage {
  items: [RogueAp!]!
  nextCursor: String
}

"""A static route configured on the gateway."""
type Route {
  id: ID
  name: String
  targetSubnet: String
  gateway: String
  distance: Int
  enabled: Boolean!
}

"""Paginated page of static routes."""
type RoutePage {
  items: [Route!]!
  nextCursor: String
}

"""A UniFi Access schedule (weekly access window)."""
type Schedule {
  id: ID
  name: String
  weeklyPattern: JSON!
  enabled: Boolean!
}

"""Paginated page of UniFi Access schedules."""
type SchedulePage {
  items: [Schedule!]!
  nextCursor: String
}

"""A UniFi Protect sensor (motion / leak / temperature)."""
type Sensor {
  id: ID
  mac: String
  name: String
  type: String
  batteryStatus: String
  humidityStatus: String
  lightStatus: String
  motionDetectedAt: String
}

"""Paginated page of UniFi Protect sensors."""
type SensorPage {
  items: [Sensor!]!
  nextCursor: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerHost {
  """Site Manager host id"""
  id: String

  """Hardware id"""
  hardwareId: String

  """Host type, such as console or network-server"""
  type: String

  """Public IP address"""
  ipAddress: String

  """Whether the API key's account owns this host"""
  owner: Boolean

  """Whether the host is blocked"""
  isBlocked: Boolean

  """When the host was registered"""
  registrationTime: JSON

  """When the host last connected or disconnected"""
  lastConnectionStateChange: JSON

  """When the latest cloud backup was taken"""
  latestBackupTime: JSON

  """Console name"""
  name: String

  """Console hostname"""
  hostname: String

  """Connection state, such as connected"""
  state: String

  """UniFi OS or server version"""
  osVersion: String

  """Hardware model name"""
  model: String

  """Hardware short name, such as UDMPROSE"""
  shortname: String

  """Hardware firmware version"""
  firmwareVersion: String

  """Console MAC address"""
  mac: String

  """Console timezone"""
  timezone: String

  """Update release channel"""
  releaseChannel: String

  """Applications on the host"""
  applications: [SiteManagerHostApplication!]!

  """Full state reported by the host; present only when requested"""
  reportedState: JSON
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerHostApplication {
  """Application name, such as network or protect"""
  name: String

  """Application type"""
  type: String

  """Installed version"""
  version: String

  """Lifecycle state reported by the console"""
  state: String

  """Status reported by the application"""
  status: String

  """Whether the application is installed"""
  isInstalled: Boolean

  """Whether the application is running"""
  isRunning: Boolean

  """Whether initial setup is complete"""
  isConfigured: Boolean

  """Version available as an update, if any"""
  updateAvailable: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerHostDevices {
  """Site Manager host id"""
  hostId: String

  """Host name"""
  hostName: String

  """When the host last reported its devices"""
  updatedAt: JSON

  """Devices managed by the host"""
  devices: [SiteManagerManagedDevice!]!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerHostDevicesPage {
  items: [SiteManagerHostDevices!]!
  nextCursor: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerHostPage {
  items: [SiteManagerHost!]!
  nextCursor: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerIspMetricPeriod {
  """Start of the interval"""
  time: JSON

  """Average latency in milliseconds"""
  avgLatencyMs: Float

  """Maximum latency in milliseconds"""
  maxLatencyMs: Float

  """Packet loss as reported by the API"""
  packetLoss: Float

  """Download throughput in kbps"""
  downloadKbps: Float

  """Upload throughput in kbps"""
  uploadKbps: Float

  """Uptime within the interval as reported"""
  uptime: Float

  """Downtime within the interval as reported"""
  downtime: Float

  """ISP name"""
  ispName: String

  """ISP autonomous system number"""
  ispAsn: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerIspMetricSeries {
  """Site Manager host id"""
  hostId: String

  """Site Manager site id"""
  siteId: String

  """Interval of the series: 5m or 1h"""
  metricType: String

  """Aggregates over the window"""
  summary: SiteManagerIspMetricSummary!

  """Most recent periods, oldest first"""
  periods: [SiteManagerIspMetricPeriod!]!

  """Whether older periods were left out of periods"""
  periodsTruncated: Boolean!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerIspMetricSummary {
  """Number of periods in the window"""
  periodCount: Int!

  """Time of the earliest period"""
  firstTime: JSON

  """Time of the latest period"""
  lastTime: JSON

  """Mean of the periods' average latency"""
  avgLatencyMs: Float

  """Highest latency in the window"""
  maxLatencyMs: Float

  """Mean packet loss"""
  avgPacketLoss: Float

  """Mean download throughput in kbps"""
  avgDownloadKbps: Float

  """Mean upload throughput in kbps"""
  avgUploadKbps: Float

  """Sum of reported downtime"""
  totalDowntime: Float

  """Number of periods reporting any downtime"""
  periodsWithDowntime: Int!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerIspMetrics {
  items: [SiteManagerIspMetricSeries!]!
  nextCursor: String
  count: Int!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerIspMetricsQueryResult {
  items: [SiteManagerIspMetricSeries!]!
  nextCursor: String
  count: Int!
  partial: Boolean!
  message: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerManagedDevice {
  """Site Manager device id"""
  id: String

  """Device MAC address"""
  mac: String

  """Device name"""
  name: String

  """Device model"""
  model: String

  """Device short name"""
  shortname: String

  """Device IP address"""
  ip: String

  """Product line, such as network or protect"""
  productLine: String

  """Connection status"""
  status: String

  """Firmware version"""
  version: String

  """Firmware status, such as upToDate"""
  firmwareStatus: String

  """Firmware version available as an update"""
  updateAvailable: String

  """Whether the device is the host console itself"""
  isConsole: Boolean

  """Whether the device is managed by the host"""
  isManaged: Boolean

  """When the device last started"""
  startupTime: JSON

  """When the device was adopted"""
  adoptionTime: JSON

  """Operator note on the device"""
  note: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
input SiteManagerMetricsSiteInput {
  hostId: String!
  siteId: String!
  beginTimestamp: String = null
  endTimestamp: String = null
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerQuery {
  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  hosts(pageSize: Int = null, cursor: String = null): SiteManagerHostPage!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  host(hostId: String!, includeReportedState: Boolean! = false): SiteManagerHost!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  sites(pageSize: Int = null, cursor: String = null): SiteManagerSitePage!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  devices(hostIds: [String!] = null, updatedSince: String = null, pageSize: Int = null, cursor: String = null): SiteManagerHostDevicesPage!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  ispMetrics(metricType: String! = "1h", duration: String = null, beginTimestamp: String = null, endTimestamp: String = null, periodLimit: Int! = 12): SiteManagerIspMetrics!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  queryIspMetrics(sites: [SiteManagerMetricsSiteInput!]!, metricType: String! = "1h", periodLimit: Int! = 12): SiteManagerIspMetricsQueryResult!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  sdwanConfigs: SiteManagerSdwanConfigList!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  sdwanConfig(configId: String!): SiteManagerSdwanConfig!

  """
  A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
  """
  sdwanConfigStatus(configId: String!): SiteManagerSdwanConfigStatus!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerSdwanConfig {
  """SD-WAN configuration id"""
  id: String

  """Configuration name"""
  name: String

  """Topology type"""
  type: String

  """Topology variant"""
  variant: String

  """Configuration settings"""
  settings: JSON!

  """Hub members"""
  hubs: [JSON!]!

  """Spoke members"""
  spokes: [JSON!]!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerSdwanConfigList {
  items: [SiteManagerSdwanConfigSummary!]!
  nextCursor: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerSdwanConfigStatus {
  """SD-WAN configuration id"""
  id: String

  """Fingerprint of the generated configuration"""
  fingerprint: String

  """Status of configuration generation"""
  generateStatus: String

  """When the status was last updated"""
  updatedAt: JSON

  """When the configuration was generated"""
  lastGeneratedAt: JSON

  """Configuration-level errors"""
  errors: [JSON!]!

  """Configuration-level warnings"""
  warnings: [JSON!]!

  """Per-hub status"""
  hubs: [JSON!]!

  """Per-spoke status"""
  spokes: [JSON!]!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerSdwanConfigSummary {
  """SD-WAN configuration id"""
  id: String

  """Configuration name"""
  name: String

  """Topology type"""
  type: String
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerSite {
  """Site Manager site id"""
  siteId: String

  """Site Manager id of the host running the site"""
  hostId: String

  """Site name key"""
  name: String

  """Site display name"""
  description: String

  """Site timezone"""
  timezone: String

  """MAC address of the site's gateway"""
  gatewayMac: String

  """The account's permission on the site"""
  permission: String

  """Whether the API key's account owns the site"""
  isOwner: Boolean

  """Device, client and configuration counts"""
  counts: JSON!

  """Gateway model and threat-inspection state"""
  gateway: JSON!

  """ISP name and organization"""
  isp: JSON!

  """WAN uptime percentage"""
  wanUptimePercent: Float

  """Recent internet issue intervals, most recent API order"""
  internetIssues: [JSON!]!
}

"""
A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
"""
type SiteManagerSitePage {
  items: [SiteManagerSite!]!
  nextCursor: String
}

"""Controller site settings."""
type SiteSettings {
  siteId: String
  name: String
  role: String
  country: Int
}

"""A UniFi Protect smart-detection event row."""
type SmartDetection {
  id: ID
  type: String
  start: String
  end: String
  score: Int
  smartDetectTypes: [String!]!
  camera: ID
  thumbnail: ID
  recognizedPersonId: ID
  recognizedPersonName: String
  recognizedPersonConfidence: Int
  recognizedPlateText: String
  recognizedPlateGroupId: ID
  recognizedPlateConfidence: Int
  detectedThumbnailId: ID
}

"""Paginated page of UniFi Protect smart-detections."""
type SmartDetectionPage {
  items: [SmartDetection!]!
  nextCursor: String
}

"""Metadata for a JPEG snapshot captured from a Protect camera."""
type Snapshot {
  sizeBytes: Int
  contentType: String
  capturedAt: String
  url: String
  snapshotUrl: String
  imageBase64: String
}

"""Controller SNMP settings."""
type SnmpSettings {
  enabled: Boolean!
  community: String
  enabledV3: Boolean
  username: String
  xPassword: String
  port: Int
  version: String
}

"""A speedtest result entry."""
type SpeedtestResult {
  """When the test ran, in epoch milliseconds."""
  timestamp: BigInt
  downloadMbps: Float
  uploadMbps: Float
  latencyMs: Float

  """
  WAN the test ran on (e.g. WAN, WAN2); null when the controller does not say.
  """
  wanNetworkgroup: String

  """Gateway interface the test ran on (e.g. eth8)."""
  interfaceName: String
}

"""Paginated page of speedtest result entries."""
type SpeedtestResultPage {
  items: [SpeedtestResult!]!
  nextCursor: String
}

"""Speedtest status reported by a UniFi gateway."""
type SpeedtestStatus {
  status: String
  downloadMbps: Float
  uploadMbps: Float
  latencyMs: Int
  lastRun: Int
}

"""A single timeseries point: {ts: <ms>, ...metrics}."""
type StatPoint {
  ts: Int!
}

"""Switch capabilities (caps dict + STP / dot1x flags)."""
type SwitchCapabilities {
  name: String
  model: String
  switchCaps: JSON
  stpVersion: String
  stpPriority: String
  jumboframeEnabled: Boolean
  dot1xPortctrlEnabled: Boolean
}

"""Wrapper dict containing port-override rows for a switch."""
type SwitchPorts {
  name: String
  model: String
  portOverrides: [PortOverrideRow!]!
}

"""Controller system information."""
type SystemInfo {
  name: String
  version: String
  hostname: String
  uptime: Int
  numDevices: Int
  numClients: Int
  updateAvailable: Boolean
  cpuPercent: Float
  memoryPercent: Float
}

"""Teleport VPN settings; only subnet_cidr is writable."""
type TeleportSettings {
  enabled: Boolean
  subnetCidr: String
  id: ID
  siteId: String
}

"""
Site-wide threat management (IDS/IPS) and traffic identification settings.
"""
type ThreatManagementSettings {
  """
  Raw IPS operation mode string from controller (e.g. 'disabled', 'ids', 'ips', 'ipsInline').
  """
  ipsMode: String

  """
  Normalized enabled state: true for known active modes, false for disabled, null for unknown/missing.
  """
  enabled: Boolean

  """Enabled threat category codes (null when absent from controller)."""
  enabledCategories: [String!]

  """Protected network IDs (null when absent from controller)."""
  enabledNetworks: [String!]

  """
  Traffic identification (DPI) enabled state (strict boolean, null if missing/malformed).
  """
  trafficIdentificationEnabled: Boolean

  """
  Device fingerprinting enabled state (strict boolean, null if missing/malformed).
  """
  deviceFingerprintingEnabled: Boolean

  """Advanced filtering preference; null when missing or malformed."""
  advancedFilteringPreference: String
}

"""
CyberSecure summary and gateway signature status for a selected period.
"""
type ThreatPosture {
  """HOUR, DAY, WEEK, or MONTH."""
  period: String!

  """Enterprise status; null if unknown."""
  enterprise: Boolean

  """Subscription status; null if unknown."""
  hasSubscription: Boolean

  """IPS enabled state; null if unknown."""
  ipsEnabled: Boolean

  """Activation state; null if unknown."""
  isActivating: Boolean

  """Scanned bytes during the period; null if unknown."""
  scannedBytes: BigInt

  """Signature capacity; null if unknown."""
  signatureCapacity: BigInt

  """Signature count; null if unknown."""
  signatures: BigInt

  """Threat count during the period; null if unknown."""
  threats: BigInt

  """Summary update time in Unix milliseconds; null if unknown."""
  updatedTimestamp: BigInt

  """Allowlisted per-gateway signature status."""
  gatewaySignatures: [GatewaySignature!]!
}

"""A top-traffic client entry."""
type TopClient {
  mac: String
  hostname: String

  """Bytes the network transmitted to this client (the client's download)."""
  txBytes: BigInt

  """Bytes the network received from this client (the client's upload)."""
  rxBytes: BigInt

  """Bytes uploaded by this client (same value as rx_bytes)."""
  uploadBytes: BigInt

  """Bytes downloaded by this client (same value as tx_bytes)."""
  downloadBytes: BigInt
  totalBytes: BigInt

  """
  'report' when summed over the requested window; 'live_counters' when cumulative since association and not scoped to the window.
  """
  source: String
}

"""A single UniFi traffic-flow record."""
type TrafficFlow {
  id: String
  action: String
  risk: String
  service: String
  protocol: String
  direction: String
  count: Int
  durationMilliseconds: Int
  time: BigInt
  flowStartTime: BigInt
  flowEndTime: BigInt
  bytesTotal: BigInt
  bytesRx: BigInt
  bytesTx: BigInt
  source: TrafficFlowEndpoint!
  destination: TrafficFlowEndpoint!
  policies: [TrafficFlowPolicy!]!
}

"""One side (source or destination) of a traffic flow."""
type TrafficFlowEndpoint {
  name: String
  mac: String
  ip: String
  port: Int
  networkName: String
  zoneName: String

  """
  Region (uppercase country code) the controller records for the address; null if none.
  """
  region: String
  domains: [String!]!
}

"""Paginated page of UniFi traffic flows."""
type TrafficFlowPage {
  items: [TrafficFlow!]!
  nextCursor: String
}

"""A policy that matched a traffic flow."""
type TrafficFlowPolicy {
  id: String

  """Policy type, such as FIREWALL or INTRUSION_PREVENTION."""
  type: String

  """Policy subtype, such as SIGNATURE or CONNTRACK."""
  internalType: String
  name: String

  """IPS category; null unless the policy is an IPS match."""
  ipsCategory: String
}

"""Aggregated Insights > Flows summary (latest-statistics)."""
type TrafficFlowStatistics {
  allowedCountByRisk: JSON!
  blockedCountByRisk: JSON!
  allowedCountByRegionByRisk: JSON!
  allCountByRegion: JSON!
  blockedCountByRegion: JSON!
  topClients: [TrafficFlowTopClient!]!
  topBlockedClients: [TrafficFlowTopClient!]!
  topDestinations: [TrafficFlowTopDestination!]!
  topApplications: [TrafficFlowTopApplication!]!
  topBlockedPolicies: [TrafficFlowTopPolicy!]!
}

"""An application in a traffic-flow Top-Talkers ranking (by bytes)."""
type TrafficFlowTopApplication {
  """
  Low V2 traffic-flow application ID. Scoped to the V2 traffic-flow tool family; do not pass it to Integration API DPI tools.
  """
  applicationId: Int

  """
  V2 traffic-flow category ID used for one-way name annotation. Scoped to the V2 traffic-flow tool family; do not pass it to Integration API DPI tools.
  """
  categoryId: Int
  bytes: BigInt
  applicationName: String
  categoryName: String
}

"""A client in a traffic-flow Top-Talkers ranking."""
type TrafficFlowTopClient {
  count: Int
  clientMac: String
  clientName: String
}

"""A destination in a traffic-flow Top-Talkers ranking."""
type TrafficFlowTopDestination {
  count: Int
  destination: String
  mostFrequentRegion: String
}

"""A policy in a traffic-flow blocked-flow ranking."""
type TrafficFlowTopPolicy {
  count: Int
  policyId: String
  policyName: String
  policyType: String
}

"""A traffic-route policy (V2 /trafficroutes entry)."""
type TrafficRoute {
  id: ID
  name: String
  matchingTarget: String
  networkId: String
  nextHop: String
  enabled: Boolean!
  killSwitchEnabled: Boolean
  sourceTargets: JSON
  destinationTargets: JSON
}

"""Paginated page of traffic-route policies."""
type TrafficRoutePage {
  items: [TrafficRoute!]!
  nextCursor: String
}

"""A UniFi Access user (employee / cardholder)."""
type User {
  id: ID
  name: String
  employeeId: String
  status: String
  role: String
  createdAt: String

  """Credentials registered for this user."""
  credentials: [Credential!]!
}

"""A QoS user group (V1 /rest/usergroup entry)."""
type UserGroup {
  id: ID
  name: String
  qosRateMaxDown: Int
  qosRateMaxUp: Int
}

"""Paginated page of QoS user groups."""
type UserGroupPage {
  items: [UserGroup!]!
  nextCursor: String
}

"""Paginated page of UniFi Access users."""
type UserPage {
  items: [User!]!
  nextCursor: String
}

"""Wrapper for protect_list_viewers — {viewers, count}."""
type ViewerList {
  viewers: JSON
  count: Int
}

"""
A time-bounded UniFi Access Developer API visitor pass. Its UUID is scoped to the Access Developer API visitor family and must not be passed to other Access user or credential operations.
"""
type Visitor {
  id: ID
  name: String
  firstName: String
  lastName: String
  hostUserId: String
  validFrom: String
  validUntil: String
  status: String
  credentialCount: Int
  email: String
  phone: String
  company: String
  visitReason: String
  remarks: String
  accessPolicyIds: [String!]
}

"""Paginated page of UniFi Access visitors."""
type VisitorPage {
  items: [Visitor!]!
  nextCursor: String
}

"""A hotspot voucher (V1 /stat/voucher entry)."""
type Voucher {
  id: ID
  code: String
  status: String
  duration: Int
  qosOverwrite: Boolean!
  createdAt: Int
  usedAt: Int
}

"""Paginated page of hotspot vouchers."""
type VoucherPage {
  items: [Voucher!]!
  nextCursor: String
}

"""A configured VPN client (outbound tunnel)."""
type VpnClient {
  id: ID
  name: String
  type: String
  enabled: Boolean!
  serverAddress: String
  lastHandshake: Int
}

"""Paginated page of VPN clients."""
type VpnClientPage {
  items: [VpnClient!]!
  nextCursor: String
}

"""A configured VPN server (inbound tunnel)."""
type VpnServer {
  id: ID
  name: String
  type: String
  enabled: Boolean!
  listenPort: Int
  allowedSubnets: [String!]
  alternateAddressEnabled: Boolean
  alternateAddress: String
}

"""Paginated page of VPN servers."""
type VpnServerPage {
  items: [VpnServer!]!
  nextCursor: String
}

"""A UniFi WLAN/SSID configuration."""
type Wlan {
  id: ID
  name: String
  settingPreference: String
  enabled: Boolean
  security: String
  networkId: String
  hideSsid: Boolean
  vlanId: Int
  xPassphrase: String
  guestPolicy: Boolean
  usergroupId: String
  fastRoamingEnabled: Boolean
  rrmEnabled: Boolean
  roamingAssistantNaEnabled: Boolean
  roamingAssistantNaRssi: Int
  roamingAssistant6eEnabled: Boolean
  roamingAssistant6eRssi: Int
  pmfMode: String
  wpa3Support: Boolean
  wpa3Transition: Boolean
  macFilterEnabled: Boolean
  macFilterPolicy: String
  macFilterList: [String!]
  scheduleEnabled: Boolean
  scheduleReversed: Boolean
  schedule: [String!]
  scheduleWithDuration: [WlanScheduleWindow!]
  l2Isolation: Boolean
  wlanBand: String
  multicastEnhanceEnabled: Boolean
  dtimMode: String
  dtimNa: Int
  dtimNg: Int
  minrateSettingPreference: String
  minrateNgEnabled: Boolean
  minrateNgDataRateKbps: Int
  minrateNaEnabled: Boolean
  minrateNaDataRateKbps: Int
  groupRekey: Int
  uapsdEnabled: Boolean
  proxyArp: Boolean
  iappEnabled: Boolean
  apGroupIds: [String!]
  apGroupMode: String
  sourceApi: String

  """
  Public Integration inventory UUID, not a legacy resource ID. These IDs are scoped to the Integration inventory tool family — do not pass them to legacy resource tools.
  """
  integrationId: ID
}

"""Paginated page of WLAN/SSID configurations."""
type WlanPage {
  items: [Wlan!]!
  nextCursor: String
}

"""A recurring WLAN schedule window."""
type WlanScheduleWindow {
  durationMinutes: Int!
  name: String
  startDaysOfWeek: [String!]!
  startHour: Int!
  startMinute: Int!
}

```


## Query namespaces


### `query.access`


Read-only access to UniFi Access resources.


**Fields:**

- `activitySummary: ActivitySummary`  — Get the access activity histogram summary.
- `credential: Credential`  — Look up a single Access credential by id.
- `credentials: CredentialPage!`  — List Access credentials (NFC / PIN / etc., paginated).
- `device: AccessDevice`  — Look up a single Access device by id.
- `deviceConfigs: AccessDeviceConfigPage!`  — List a device's config/settings entries (e.g. reader voice greeting). Secrets redacted.
- `devices: AccessDevicePage!`  — List Access devices (readers / hubs / locks, paginated).
- `door: Door`  — Look up a single Access door by id.
- `doorGroups: DoorGroupPage!`  — List Access door groups (paginated).
- `doorStatus: DoorStatus`  — Get the live status (lock state + last event) of a door.
- `doors: DoorPage!`  — List doors on the Access controller (paginated).
- `event: AccessEvent`  — Look up a single Access event by id.
- `events: AccessEventPage!`  — List Access events by system-log topic, paginated most recent first. Use unlocks for door grants and open/close history, access_denial for refused attempts, ring for doorbells, or updates, critical, admin, and admin_activity.
- `health: AccessHealth`  — Get the Access health probe summary.
- `policies: PolicyPage!`  — List Access policies (who-can-access-what bindings).
- `policy: Policy`  — Look up a single Access policy by id.
- `schedules: SchedulePage!`  — List Access schedules (weekly access windows).
- `systemInfo: AccessSystemInfo`  — Get the Access application info (name + version + host).
- `users: UserPage!`  — List Access users (employees / cardholders, paginated).
- `visitor: Visitor`  — Look up one Access Developer API visitor using a UUID returned by the visitor family; IDs from other Access user or credential operations are not accepted.
- `visitors: VisitorPage!`  — List Access Developer API visitors. Returned UUIDs are scoped to the visitor family and must not be passed to other Access user or credential operations.


### `query.drive`


Read-only access to UniFi Drive resources.


**Fields:**

- `diskStats: DriveDiskStats!`  — Each disk's temperature, throughput and bad sectors over the last hours (1 to 2160), summarized per disk, with per-bucket samples a query selects only when it needs them. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `disks: [DriveDisk!]!`  — Drive bays and SSD cache slots with the disk in each and its SMART health. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `fanProfile: DriveFanProfile!`  — The NAS's fan mode and the modes it offers. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `fileServices: DriveFileServices!`  — Whether SMB, NFS and Time Machine are on, and the interfaces clients connect to. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `groups: [DriveGroup!]!`  — The UniFi OS user groups that shared drive access can be granted to. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `logs: DriveLogPage!`  — One page of the NAS's system log, newest first. Pass nextCursor back as cursor, with the same filters, for the next page. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `networkThroughput: DriveNetworkThroughput!`  — The NAS's network throughput right now, in KB/s. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `nfsConnections: [DriveNfsConnection!]!`  — NFS clients allowed to mount shared drives, with their export paths. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `rsyncSettings: DriveRsyncSettings!`  — The rsync service, its account (never its password) and whether SSH is on. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `sharedDrive: DriveSharedDrive!`  — One shared drive by id. Drive omits the protection flags and member count that the list includes. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `sharedDrives: [DriveSharedDrive!]!`  — Shared drives. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `smbAdvancedSettings: DriveSmbAdvancedSettings!`  — Whether SMB Trash for personal drives is on, and whether every personal drive could move to it. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `snapshotOverview: DriveSnapshotOverview!`  — Every shared and personal drive's snapshot settings and state. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `snapshots: [DriveSnapshot!]!`  — One shared drive's snapshots, newest first, by the shared drive's name, not its id. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `storagePools: [DriveStoragePool!]!`  — Storage pools and their RAID groups. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `storageUsage: [DriveStoragePoolUsage!]!`  — Each storage pool's used space, split by what uses it. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `systemInfo: DriveSystemInfo!`  — Identity, firmware and health of the NAS console. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.
- `users: [DriveUser!]!`  — The NAS's users. UniFi Drive read, through the NAS console session. These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools.


### `query.health`


Liveness probe; mirrors GET /v1/health/ready.


**Fields:**

- `ok: Boolean!`
- `pythonVersion: String!`
- `version: String!`


### `query.innerspace`


Read-only access to UniFi InnerSpace resources.


**Fields:**

- `accessPoints: [InnerSpaceAccessPoint!]!`  — InnerSpace access points. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `floorPlans: [InnerSpaceFloorPlan!]!`  — InnerSpace floor plans. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `inventory: [InnerSpaceInventoryDevice!]!`  — Adopted devices not yet placed on a plan. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `placedDevices: InnerSpacePlacedDevicePage!`  — Devices placed on one InnerSpace floor plan. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `planAsset: InnerSpacePlanAsset!`  — Image metadata of one InnerSpace floor plan. The image itself is read through the InnerSpace MCP server, never through this API. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `project: InnerSpaceProject!`  — The InnerSpace project. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `status: InnerSpaceStatus!`  — Whether InnerSpace is installed and running on the console. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `switches: [InnerSpaceSwitch!]!`  — InnerSpace switches. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.
- `walls: InnerSpaceWallPage!`  — Walls of one InnerSpace floor plan. UniFi InnerSpace read, through the console session. These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools.


### `query.network`


Read-only access to UniFi Network resources.


**Fields:**

- `aclRule: AclRule`  — Look up a single ACL rule by id.
- `aclRules: AclRulePage!`  — List ACL rules on the given controller/site (paginated).
- `activeRoutes: ActiveRoutePage!`  — List the gateway's active kernel routing-table entries (paginated).
- `alarms: AlarmPage!`  — List controller alarms (paginated).
- `alerts: EventLogPage!`  — List active alerts (paginated).
- `anomalies: EventLogPage!`  — List recent anomalies (paginated).
- `apGroup: ApGroup`  — Look up a single AP group by id.
- `apGroups: ApGroupPage!`  — List AP groups on the given controller/site (paginated).
- `autobackupSettings: AutoBackupSettings`  — Get auto-backup schedule + retention settings.
- `availableChannels: [AvailableChannel!]!`  — List wireless channels allowed by the regulatory domain.
- `backups: BackupPage!`  — List controller backups (paginated).
- `blockedClients: BlockedClientPage!`  — List clients currently blocked from the network (paginated).
- `client: Client`  — Look up a single client by MAC address.
- `clientByIp: ClientLookup`  — Look up a client by IP address (online-presence check).
- `clientDpiTraffic: [StatPoint!]!`  — Per-client DPI traffic breakdown.
- `clientGroup: ClientGroup`  — Look up a single network member client group by id.
- `clientGroups: ClientGroupPage!`  — List network member client groups on the given controller/site (paginated).
- `clientSessions: ClientSessionPage!`  — List a client's association sessions (paginated).
- `clientStats: [StatPoint!]!`  — Per-client stats timeseries (by MAC).
- `clientWifiDetails: ClientWifiDetails`  — Get a client's current WiFi parameters (signal, rates).
- `clients: ClientPage!`  — List clients on the given controller/site (paginated).
- `contentFilter: ContentFilter`  — Look up a single content filter by id.
- `contentFilters: ContentFilterPage!`  — List content filters on the given controller/site (paginated).
- `dashboardStats: [StatPoint!]!`  — Site dashboard timeseries (all-points).
- `device: Device`  — Look up a single device by MAC address.
- `deviceRadio: DeviceRadio`  — Get the radio configuration for a UniFi device with radios.
- `deviceStats: [StatPoint!]!`  — Per-device stats timeseries (by MAC).
- `devices: DevicePage!`  — List devices on the given controller/site (paginated).
- `dnsRecord: DnsRecord`  — Look up a single DNS record by id.
- `dnsRecords: DnsRecordPage!`  — List static DNS records on the given controller/site (paginated).
- `dpiApplications: DpiApplicationPage!`  — List DPI applications (paginated).
- `dpiCategories: DpiCategoryPage!`  — List DPI categories (paginated).
- `dpiStats: DpiStats`  — DPI restriction rules (applications) and groups (categories); not traffic.
- `dynamicDns: DynamicDnsPage!`  — List Dynamic DNS provider entries on the given controller/site (paginated).
- `dynamicDnsEntry: DynamicDns`  — Look up a single Dynamic DNS entry by id.
- `eventLog: EventLogPage!`  — List recent controller events (paginated).
- `eventTypes: EventTypes`  — Get exact event keys sampled from the controller's 1,000 most recent events within the last 7 days.
- `firewallGroup: FirewallGroup`  — Look up a single firewall group by id.
- `firewallGroups: FirewallGroupPage!`  — List firewall address/port groups (paginated).
- `firewallPolicies: FirewallRulePage!`  — List firewall policies/rules on the given controller/site (paginated).
- `firewallPolicy: FirewallRule`  — Look up a single firewall policy/rule by id.
- `firewallPolicyOrder: FirewallPolicyOrder!`  — Get the order of the user-defined firewall policies for a source/destination zone pair through the V2 API. Requires Network session credentials. These IDs are scoped to the V2 firewall policy tool family — do not pass them to the Integration API ordering queries or actions.
- `firewallPolicyOrdering: FirewallPolicyOrdering!`  — Get user-defined firewall policy ordering for a source/destination zone pair. Returns policy IDs from the UniFi integration API (UUIDs); these IDs are scoped to the ordering tool family and do NOT correspond to the policy IDs returned by firewallPolicies or other controller-API firewall queries. Requires a UniFi API key (UNIFI_API_KEY).
- `firewallZones: [FirewallZone!]!`  — List firewall zones (typically a small flat list — no pagination).
- `gatewaySettings: GatewaySettings`  — Get gateway (USG) security / NAT / connection-tracking settings.
- `gatewayStats: [StatPoint!]!`  — Gateway stats timeseries.
- `incidentEvidence: IncidentEvidence!`  — Collect bounded, read-only Network event evidence for one incident window as a unifi-incident-evidence-view (coverage plus bounded record citations), or with detail full the whole unifi-incident-evidence document. Stops at the first spent budget and says so; check coverage_complete before treating an empty result as an all-clear. Not cached.
- `ipsEvents: EventLogPage!`  — List recent IPS/IDS events (paginated).
- `ipsSuppressions: IpsSuppressions!`  — List IPS signature suppressions and detection exclusions.
- `legacyFirewallRules: [LegacyFirewallRule!]!`  — List legacy (pre-zone-based) firewall rules. Sites still running the legacy engine return no zone-based policies or zones, so an empty firewallPolicies result does not mean no firewall rules are configured — check here as well.
- `lldpNeighbors: LldpNeighbors`  — Get LLDP neighbors reported by a switch.
- `mdnsSettings: MdnsSettings`  — Get site-wide mDNS service settings and read-only network scope.
- `mgmtSettings: MgmtSettings`  — Get device management (mgmt) settings: device SSH, debug tools, automatic upgrades.
- `natRule: NatRule`  — Get a V2 NAT rule by its NAT-family ID; do not use port-forward or Integration API IDs.
- `natRules: NatRulePage!`  — List V2 NAT rules in descending controller ID order. These IDs are scoped to the V2 NAT tool family — do not pass them to port-forward or Integration API tools.
- `networkDetail: Network`  — Look up a single LAN/VLAN network by id. (Named ``networkDetail`` because ``network`` is reserved for the namespace.)
- `networkHealth: [NetworkHealth!]!`  — Get the controller's network-health subsystems list.
- `networkReferences: NetworkReferences`  — What references a network: Wi-Fi networks, port profiles, switch-port overrides, V2 firewall policies and clients. network_id is the network's _id from the networks field. Each family is read on its own; a family whose read failed is listed in unavailable instead of being reported as empty.
- `networkStats: [StatPoint!]!`  — Network-wide stats timeseries.
- `networks: NetworkPage!`  — List configured LAN/VLAN networks on the given controller/site (paginated).
- `oonPolicies: OonPolicyPage!`  — List OON (out-of-network) policies (paginated).
- `oonPolicy: OonPolicy`  — Look up a single OON policy by id.
- `pduOutlets: PduOutlets`  — Get per-outlet state for a UniFi Smart Power PDU (UP6 / USP-Strip).
- `portForward: PortForward`  — Look up a single port forward by id.
- `portForwards: PortForwardPage!`  — List port forwards on the given controller/site (paginated).
- `portProfile: PortProfile`  — Look up a single switch port profile by id.
- `portProfiles: PortProfilePage!`  — List switch port profiles on the given controller/site (paginated).
- `portStats: PortStats`  — Get the per-port stats wrapper for a switch (name/model + port_table).
- `qosRule: QosRule`  — Look up a single QoS rule by id.
- `qosRules: QosRulePage!`  — List QoS rules on the given controller/site (paginated).
- `rfScanResults: [RfScanResult!]!`  — List RF-scan results for a specific access point.
- `rogueAps: RogueApPage!`  — List rogue (unknown) APs detected within a window (paginated).
- `route: Route`  — Look up a single static route by id.
- `routes: RoutePage!`  — List configured static routes (paginated).
- `siteDpiTraffic: [StatPoint!]!`  — Site-wide DPI traffic breakdown.
- `siteSettings: SiteSettings`  — Get site-level settings (locale, timezone, advanced).
- `snmpSettings: SnmpSettings`  — Get SNMP settings.
- `speedtestResults: SpeedtestResultPage!`  — List recent speedtest results (paginated).
- `speedtestStatus: SpeedtestStatus`  — Get the gateway speedtest status (idle/running + last results).
- `switchCapabilities: SwitchCapabilities`  — Get switch capabilities (caps dict + STP / dot1x flags).
- `switchPorts: SwitchPorts`  — Get the port-override wrapper for a switch (name/model + per-port overrides).
- `systemInfo: SystemInfo`  — Get controller system info (build, uptime, hardware).
- `teleportSettings: TeleportSettings`  — Get Teleport VPN settings: enabled state and client address range (subnet_cidr).
- `threatManagementSettings: ThreatManagementSettings`  — Get site-wide threat management (IDS/IPS) and traffic identification settings.
- `threatPosture: ThreatPosture`  — Get CyberSecure threat posture for HOUR, DAY, WEEK, or MONTH using a Network session.
- `topClients: [TopClient!]!`  — List top-traffic clients within a window.
- `trafficFlowStatistics: TrafficFlowStatistics!`  — Aggregated Insights > Flows summary (risk/region counts + Top-Talkers).
- `trafficFlows: TrafficFlowPage!`  — Query historical traffic flows (Insights > Flows), paginated.
- `trafficRoute: TrafficRoute`  — Look up a single traffic-route policy by id.
- `trafficRoutes: TrafficRoutePage!`  — List traffic-route policies (V2 /trafficroutes) (paginated).
- `userGroup: UserGroup`  — Look up a single QoS user group by id.
- `userGroups: UserGroupPage!`  — List QoS user groups (V1 /rest/usergroup) on the given controller/site (paginated).
- `voucher: Voucher`  — Look up a single hotspot voucher by id.
- `vouchers: VoucherPage!`  — List hotspot vouchers on the given controller/site (paginated).
- `vpnClient: VpnClient`  — Look up a single VPN client by id.
- `vpnClients: VpnClientPage!`  — List configured VPN clients (outbound tunnels) (paginated).
- `vpnServer: VpnServer`  — Look up a single VPN server by id.
- `vpnServers: VpnServerPage!`  — List configured VPN servers (inbound tunnels) (paginated).
- `wlan: Wlan`  — Look up a single WLAN/SSID by id.
- `wlans: WlanPage!`  — List WLAN/SSID configurations on the given controller/site (paginated).


### `query.protect`


Read-only access to UniFi Protect resources.


**Fields:**

- `alarmCatalog: AlarmCatalog`  — Triggers and actions the Alarm Manager accepts in rules ({triggers, actions, scope}); their ids are the trigger_id/action_id values a rule takes. search filters by id, title or category; includeSchemas adds each entry's options_schema and the scope schema.
- `alarmProfiles: AlarmProfileList`  — List configured alarm profiles ({profiles, count, complete, coverageNotice}), including each profile's state and state_set_at timestamp. Use arm_compatible to determine whether a profile id can be passed to the arm and disarm actions.
- `alarmRule: AlarmRule`  — Fetch a single alarm rule (automation) by id.
- `alarmRules: AlarmRuleList`  — List configured alarm rules / Alarm Manager automations ({rules, count}).
- `alarmStatus: AlarmStatus`  — Get the alarm system arm-state snapshot.
- `camera: Camera`  — Look up a single Protect camera by id.
- `cameraAnalytics: CameraAnalytics`  — Get analytics summary for a Protect camera.
- `cameraDetectionAreas: CameraDetectionAreas`  — List a camera's crossing lines, smart-detect zones and loiter zones (id, name, kind, objectTypes, and direction for lines), read fresh from the NVR.
- `cameraStreams: CameraStreams`  — Get the stream catalog (channels + RTSPS URLs) for a camera.
- `cameras: CameraPage!`  — List cameras on the Protect controller (paginated).
- `chimes: ChimePage!`  — List paired Protect chimes (paginated).
- `detectionSearchLabels: DetectionSearchLabels!`  — The detection-search filter vocabulary ('Find Anything' label groups).
- `event: Event`  — Look up a single Protect event by id.
- `eventThumbnail: EventThumbnail`  — Get the thumbnail for a Protect event.
- `events: EventPage!`  — List Protect events (paginated, most recent first).
- `firmwareStatus: FirmwareStatus`  — Get firmware status for the NVR plus its devices.
- `health: ProtectHealth`  — Get the NVR health snapshot (cpu / memory / storage).
- `incidentEvidence: IncidentEvidence!`  — Collect bounded, read-only Protect event evidence for one incident window as a unifi-incident-evidence-view (coverage plus bounded record citations), or with detail full the whole unifi-incident-evidence document. Each camera ID is its own source. Stops at the first spent budget and says so; check coverage_complete before treating an empty result as an all-clear. Not cached.
- `knownFaces: KnownFacePage!`  — List assigned Protect Known Faces / named face recognition groups.
- `knownLicensePlates: KnownLicensePlatePage!`  — List UniFi Protect license-plate identities (vehicle recognition groups). Each entry's id is the value to use in a `license_plate_known` alarm-rule condition.
- `lights: LightPage!`  — List Protect lights (PIR-triggered floodlights).
- `liveviews: LiveviewPage!`  — List Protect liveviews (multi-camera grid layouts).
- `recordingStatus: RecordingStatusList`  — Get current recording state for one or all cameras ({cameras, count}).
- `recordings: RecordingPage!`  — List Protect recording windows for a camera. UniFi Protect exposes a single continuous recording window per camera.
- `searchDetections: [SmartDetection!]!`  — Search detections across cameras via Protect's 'Find Anything' filter vocabulary. Pass labels of the form 'prefix:value' (e.g. 'vehicleType:truck'); use detectionSearchLabels to discover legal values.
- `sensors: SensorPage!`  — List Protect sensors (motion / leak / temperature).
- `smartDetections: SmartDetectionPage!`  — List Protect smart-detection events (paginated, most recent first).
- `snapshot: Snapshot`  — Capture a JPEG snapshot from a camera (metadata only).
- `systemInfo: ProtectSystemInfo`  — Get the NVR-level system info snapshot.
- `viewers: ViewerList`  — List Protect viewers ({viewers, count}).


### `query.sitemanager`


A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.


**Fields:**

- `devices: SiteManagerHostDevicesPage!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `host: SiteManagerHost!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `hosts: SiteManagerHostPage!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `ispMetrics: SiteManagerIspMetrics!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `queryIspMetrics: SiteManagerIspMetricsQueryResult!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `sdwanConfig: SiteManagerSdwanConfig!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `sdwanConfigStatus: SiteManagerSdwanConfigStatus!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `sdwanConfigs: SiteManagerSdwanConfigList!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
- `sites: SiteManagerSitePage!`  — A READ key sees every resource the cloud account can see. These IDs are scoped to the Site Manager tool family — do not pass them to other resource tools.
