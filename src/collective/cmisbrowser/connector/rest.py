# -*- coding: utf-8 -*-
# Copyright (c) 2011 Infrae. All rights reserved.
# See also LICENSE.txt
# $Id$

import time
import logging

from cmislib.model import CmisClient

from plone.memoize import ram
from zope.interface import implements

from collective.cmisbrowser.errors import CMISConnectorError
from collective.cmisbrowser.interfaces import ICMISConnector
from collective.cmisbrowser.cmis.result import CMISFileResult


# Disable the rather verbose cmislib logger.
cmis_logger = logging.getLogger('cmislib.model')
cmis_logger.setLevel(logging.WARN)


class RESTConnectorError(CMISConnectorError):
    pass


def rest_cache(wrapped):
    # Default cache time is two minute

    def get_cache_key(method, self, id_or_path, *args, **kwargs):
        return '#'.join((
                self._settings.UID(),
                self._repository_id,
                id_or_path.encode('ascii', 'xmlcharrefreplace'),
                str(time.time() // (2 *60))))

    return ram.cache(get_cache_key)(wrapped)


def cmis_object_to_dict(cmis_object, root=False):
    # Copy the dict to prevent modification of the cached cmis_object.
    properties = cmis_object.getProperties().copy()
    if root:
        if isinstance(root, bool) or root == properties['cmis:objectId']:
            properties['cmis:objectTypeId'] = 'cmisbrowser:root'
    return properties


class RESTConnector(object):
    implements(ICMISConnector)

    def __init__(self, settings):
        self._settings = settings
        self._repository = None
        self._repository_id = None # Used by cache key
        self._root = None
        self._cache = {}

    def _get_cmis_object(self, cmis_id):
        # Simple connection cache used to cache cmislib object that
        # have been fetched during this connection. For lot of
        # operation, you need the original cmislib object to call
        # them. That would be sad to build them multiple times.
        if cmis_id in self._cache:
            return self._cache[cmis_id]
        cmis_object = self._repository.getObject(cmis_id)
        self._cache[cmis_id] = cmis_object
        return cmis_object

    @rest_cache
    def get_object_by_path(self, path, root=False):
        return cmis_object_to_dict(
            self._repository.getObjectByPath(path),
            root=root)

    @rest_cache
    def get_object_by_cmis_id(self, cmis_id, root=False):
        return cmis_object_to_dict(
            self._get_cmis_object(cmis_id),
            root=root)

    @rest_cache
    def get_object_children(self, cmis_id):
        convert = lambda c: cmis_object_to_dict(c)
        return map(convert, self._get_cmis_object(cmis_id).getChildren())

    @rest_cache
    def get_object_parent(self, cmis_id):
        root_id = self._root['cmis:objectId']
        if cmis_id == root_id:
            return None
        cmis_object = self._get_cmis_object(cmis_id)
        parent = cmis_object.getObjectParents()
        if not len(parent):
            return None
        return cmis_object_to_dict(parent[0].object, root=root_id)

    def get_object_parents(self, cmis_id):
        parents = []
        parent = self.get_object_parent(cmis_id)
        while parent is not None:
            parents.append(parent)
            cmis_id = parent['cmis:objectId']
            parent = self.get_object_parent(cmis_id)
        return parents

    def query_for_objects(self, query, start=None, count=None):
        convert = lambda c: cmis_object_to_dict(c)
        return map(convert, self._repository.query(query))

    def get_object_content(self, cmis_id):
        cmis_object = self._get_cmis_object(cmis_id)
        cmis_properties = cmis_object.getProperties()
        return CMISFileResult(
            filename = cmis_properties['cmis:contentStreamFileName'],
            length = cmis_properties['cmis:contentStreamLength'],
            stream=cmis_object.getContentStream(),
            mimetype=cmis_properties['cmis:contentStreamMimeType'])

    def start(self):
        if self._repository is not None:
            return self._root

        client = CmisClient(
            self._settings.repository_url,
            self._settings.repository_user,
            self._settings.repository_password)

        repositories = client.getRepositories()
        if self._settings.repository_name:
            for repository in repositories:
                if self._settings.repository_name == repository['repositoryName']:
                    break
            else:
                raise RESTConnectorError(
                    u'Unknown repository: %s' % (
                        self._settings.repository_name))
        elif len(repositories) == 1:
            repository = repositories[0]
        else:
            raise RESTConnectorError(
                u'Multiple repository available. Please select one.')
        self._repository_id = repository['repositoryId']
        self._repository = client.getRepository(self._repository_id)

        # Find root
        if self._settings.repository_path:
            self._root = self.get_object_by_path(
                self._settings.repository_path,
                root=True)
        else:
            self._root = cmis_object_to_dict(
                self._repository.getRootFolder(),
                root=True)
        return self._root
