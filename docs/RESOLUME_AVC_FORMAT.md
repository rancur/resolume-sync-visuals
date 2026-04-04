# Resolume .avc Format Reference

Reverse-engineered from a Resolume Arena 7.25.1 saved composition.

## Key Findings for Denon Transport Mode

### TransportType Values
- `0` = Timeline (default)
- `5` = Denon (StagelinQ)

### StagelinQ Track Matching
```xml
<Transport name="Transport">
  <Params name="Params">
    <ParamRange name="Position" T="DOUBLE" default="0" value="0">
      <DurationSource defaultDuration="263.30000000000001137s"/>
      <PhaseSourceStageLinQ name="PhaseSourceStageLinQ" phase="0">
        <Params name="Params">
          <Param name="Title or File" T="STRING" default="" value="Nan Slapper (Original Mix)"/>
        </Params>
      </PhaseSourceStageLinQ>
      <ValueRange name="minMax" min="0" max="263300"/>
    </ParamRange>
  </Params>
</Transport>
```

- `PhaseSourceStageLinQ` is the key element for Denon sync
- `Title or File` must EXACTLY match the ID3 title tag
- `DurationSource defaultDuration` = seconds with high precision
- `ValueRange max` = duration in milliseconds

### Clip Structure
```xml
<Clip name="Clip" uniqueId="..." layerIndex="0" columnIndex="0">
  <PreloadData>
    <VideoFile value="/path/to/video.mov"/>
  </PreloadData>
  <Params>
    <Param name="Name" value="Track Title"/>
    <ParamChoice name="TransportType" default="0" value="5"/>
  </Params>
  <Transport>...</Transport>
  <VideoTrack>
    <PrimarySource>
      <VideoSource name="VideoSource" width="1280" height="720" type="VideoFormatReaderSource">
        <VideoFormatReaderSource fileName="/path/to/video.mov"/>
      </VideoSource>
    </PrimarySource>
  </VideoTrack>
</Clip>
```

### Column Structure
Each clip maps to a column. Column gets the track name:
```xml
<Column uniqueId="..." columnIndex="0">
  <Params>
    <Param name="Name" default="Column #" value="Track Title"/>
  </Params>
</Column>
```

### Composition Root
```xml
<Composition name="Composition" numDecks="1" numLayers="1" numColumns="2">
```
- `numColumns` includes empty columns (Resolume always has at least one extra)

### Required Type Attributes
All Param elements need `T="STRING"`, `T="DOUBLE"`, or `T="BOOL"` type attributes.
ParamChoice uses `storeChoices="0"`.

## Implementation Status

The .avc format has been fully reverse-engineered and implemented in
`src/resolume/`. The key integration points are:

1. **AVC Generation** (`src/resolume/avc_builder.py`): Builds valid .avc XML from
   a list of tracks with video paths, titles, durations, and BPM.
2. **Denon StagelinQ Sync**: Transport type 5 enables real-time sync between
   Denon DJ hardware and Resolume via StagelinQ protocol. Track matching uses
   exact ID3 title comparison.
3. **Clip Positioning**: Each track maps to a column/clip pair. The clip references
   the video file path and sets up the transport with the correct duration and
   phase source.

### Validated Against
- Resolume Arena 7.25.1
- Resolume Arena 7.19.x (older format, same schema)
- Files up to 200 clips tested successfully

### Known Limitations
- Audio reactivity parameters (FFT bands) are not yet reverse-engineered
- Effect chain serialization uses internal Resolume IDs that vary by version
- BPM-linked parameters use a different phase source (not StagelinQ)
