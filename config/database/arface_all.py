#!/usr/bin/env python

import xbob.db.arface
import facereclib

database = facereclib.databases.DatabaseXBob(
    database = xbob.db.arface.Database(),
    name = 'arface',
    image_directory = "/idiap/resource/database/AR_Face/images",
    image_extension = ".ppm",
    annotation_directory = "/idiap/user/mguenther/annotations/ARface",
    annotation_type = 'eyecenter',
    protocol = 'all'
)
