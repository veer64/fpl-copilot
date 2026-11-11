/** The site's background music (Prompt W5b, 10 Nov 2026): the ONLY place the track list lives. Files sit in public/music/
 *  (gitignored, like the other media -- never committed; 128 kbps stereo MP3, loudness-normalised to about -16 LUFS /
 *  -1.5 dBTP, metadata stripped). To swap or add a track: drop the file in public/music/ and edit this list. An empty list
 *  means no music and no mute button anywhere. */

export type MusicTrack = { readonly file: string; readonly title: string; readonly artist: string };

export const MUSIC_TRACKS: readonly MusicTrack[] = [
  { file: "john-newman-love-me-again.mp3", title: "Love Me Again", artist: "John Newman" },
  { file: "saint-motel-my-type.mp3", title: "My Type", artist: "Saint Motel" },
  { file: "crystal-fighters-love-natural.mp3", title: "Love Natural", artist: "Crystal Fighters" },
  { file: "empire-of-the-sun-alive.mp3", title: "Alive", artist: "Empire of the Sun" },
  { file: "imagine-dragons-on-top-of-the-world.mp3", title: "On Top of the World", artist: "Imagine Dragons" },
  { file: "mgmt-kids.mp3", title: "Kids", artist: "MGMT" },
  { file: "smallpools-dreaming.mp3", title: "Dreaming", artist: "Smallpools" },
  { file: "the-white-stripes-seven-nation-army.mp3", title: "Seven Nation Army", artist: "The White Stripes" },
  { file: "tinie-tempah-written-in-the-stars.mp3", title: "Written in the Stars (feat. Eric Turner)", artist: "Tinie Tempah" },
  { file: "youngblood-hawke-we-come-running.mp3", title: "We Come Running", artist: "Youngblood Hawke" },
];

export const MUSIC_DIR = "/music";

export function trackUrl(t: MusicTrack): string {
  return `${MUSIC_DIR}/${t.file}`;
}
