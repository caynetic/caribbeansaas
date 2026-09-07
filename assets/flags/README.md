# Region images

Country and territory flags are local PNG images at 80 pixels wide, displayed
without cropping at up to 24 by 16 CSS pixels. Visible region names accompany
every image, so the images are decorative for screen readers.

The additional images downloaded on 2026-09-07 are `aw`, `bm`, `bq`, `cu`, `gp`,
`ht`, `kn`, `ky`, `mq`, `sr`, `tc`, and `vc`. They come from
`https://flagcdn.com/w80/{code}.png`, using the same format as the existing assets.
[Flagpedia's image API](https://flagpedia.net/download/api) documents the download
format. [Its terms](https://flagpedia.net/terms) place the flag images in the
public domain. Attribution: [Flagpedia.net](https://flagpedia.net/).

`bq.png` shows Bonaire's local flag; `mq.png` uses the red, green, and black
Martinique flag. `gp.png` is the regional Guadeloupe flag supplied by Flagpedia.
`caribbean.svg` is an original neutral globe icon in the site's colors for the
Caribbean-wide region. It does not represent a national flag.

To add another region, add its mapping and local image before rebuilding. The
renderer rejects missing assets instead of falling back to platform emoji.
